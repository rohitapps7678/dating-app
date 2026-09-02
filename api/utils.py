import math
from .models import Profile


def haversine_km(lat1, lng1, lat2, lng2):
    R     = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lng / 2) ** 2
    )
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


MAX_NEARBY_RESULTS = 100  # ✅ hard cap — bounds serialization cost & payload size


def _bounding_box(lat, lng, radius_km):
    """
    ✅ PERF: cheap degree-based bounding box so the DB (not Python) throws
    away everything that couldn't possibly be within radius_km, BEFORE
    rows even leave Postgres. 1° latitude ≈ 111km; 1° longitude shrinks
    by cos(latitude) as you move away from the equator. This box is a
    superset of the true circle (a few corner cases within the box but
    outside the circle) — the exact haversine filter below still runs on
    the (now much smaller) result set to trim those out precisely.
    """
    lat_delta = radius_km / 111.0
    lng_delta = radius_km / (111.320 * max(math.cos(math.radians(lat)), 0.01))
    return (
        lat - lat_delta, lat + lat_delta,
        lng - lng_delta, lng + lng_delta,
    )


def get_nearby_users(lat, lng, radius_km, exclude_user_id,
                     blocked_ids=None, only_live=False,
                     my_interests=None,
                     # ✅ New filter params
                     min_age=None, max_age=None,
                     show_online_only=False,
                     position=None,
                     has_room=None):

    if blocked_ids is None:
        blocked_ids = []

    lat_min, lat_max, lng_min, lng_max = _bounding_box(lat, lng, radius_km)

    qs = Profile.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
        is_complete=True,
        user__is_active=True,
        # ✅ DB-level bounding box — uses the (is_live, latitude, longitude)
        # index instead of pulling every live profile in the country into
        # Python on every request.
        latitude__gte=lat_min, latitude__lte=lat_max,
        longitude__gte=lng_min, longitude__lte=lng_max,
    ).exclude(
        user__id=exclude_user_id
    ).exclude(
        user__id__in=blocked_ids
    ).select_related("user").only(
        "id", "name", "age", "gender", "photo_url", "interests",
        "position", "has_room", "latitude", "longitude", "is_live",
        "user__id", "user__phone",
    )

    if only_live or show_online_only:
        qs = qs.filter(is_live=True)

    # ✅ Age filter
    if min_age is not None:
        qs = qs.filter(age__gte=min_age)
    if max_age is not None:
        qs = qs.filter(age__lte=max_age)

    # ✅ Position filter
    if position:
        qs = qs.filter(position=position)

    # ✅ Room filter
    if has_room is not None:
        qs = qs.filter(has_room=has_room)

    nearby = []
    for profile in qs:
        distance = haversine_km(lat, lng, profile.latitude, profile.longitude)
        if distance <= radius_km:
            profile.distance = distance
            if my_interests:
                common = set(my_interests) & set(profile.interests or [])
                total  = set(my_interests) | set(profile.interests or [])
                profile.interest_score = (
                    round(len(common) / len(total) * 100) if total else 0
                )
            else:
                profile.interest_score = 0
            nearby.append(profile)

    nearby.sort(key=lambda p: (-p.interest_score, p.distance))
    # ✅ Cap response size — without this a dense city center could return
    # thousands of rows, each of which the serializer does extra work on
    # (common_interests/interest_score), on every poll.
    return nearby[:MAX_NEARBY_RESULTS]


def get_interest_suggestions(user_profile, limit=20, blocked_ids=None):
    if not user_profile.interests:
        return []

    if blocked_ids is None:
        blocked_ids = []

    # ✅ SCALE NOTE: interest_score() needs the full interests list of both
    # sides, so it can't be computed in the DB with a plain JSONField — it
    # has to run in Python. The [:500] cap below bounds worst-case cost as
    # the live user base grows; it trades a small amount of suggestion
    # completeness (only the 500 most-recently-active live profiles are
    # considered) for a predictable, fast response time. Revisit if/when
    # interests move to a proper many-to-many table with DB-side scoring.
    profiles = Profile.objects.filter(
        is_complete=True,
        is_live=True,
        user__is_active=True,
    ).exclude(
        user=user_profile.user
    ).exclude(
        # ✅ BUG FIX: blocked users were never excluded here before, so a
        # blocked profile could still show up in "who to chat with next"
        # suggestions even though it can never appear in Nearby/Search.
        user__id__in=blocked_ids
    ).select_related("user").only(
        "id", "name", "age", "gender", "photo_url", "interests",
        "position", "has_room", "is_live", "updated_at",
        "user__id", "user__phone",
    ).order_by("-updated_at")[:500]

    scored = []
    for p in profiles:
        score = user_profile.interest_score(p)
        if score > 0:
            p.interest_score = score
            p.distance       = None
            scored.append(p)
    scored.sort(key=lambda p: -p.interest_score)
    return scored[:limit]


def api_response(data=None, message="", success=True):
    return {"success": success, "message": message, "data": data or {}}