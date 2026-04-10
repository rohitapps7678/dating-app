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

    qs = Profile.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
        is_complete=True,
        user__is_active=True,
    ).exclude(
        user__id=exclude_user_id
    ).exclude(
        user__id__in=blocked_ids
    ).select_related("user")

    if only_live:
        qs = qs.filter(is_live=True)

    # ✅ Online only filter
    if show_online_only:
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
    return nearby


def get_interest_suggestions(user_profile, limit=20):
    if not user_profile.interests:
        return []
    profiles = Profile.objects.filter(
        is_complete=True,
        is_live=True,
        user__is_active=True,
    ).exclude(user=user_profile.user).select_related("user")

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