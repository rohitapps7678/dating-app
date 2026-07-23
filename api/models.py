from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from datetime import timedelta
import uuid

INTEREST_CHOICES = [
    "Travel", "Music", "Movies", "Books", "Gaming",
    "Fitness", "Cooking", "Photography", "Art", "Dance",
    "Sports", "Hiking", "Coffee", "Fashion", "Technology",
    "Yoga", "Meditation", "Animals", "Food", "Cycling",
]

POSITION_CHOICES = [
    ("top",      "Top"),
    ("vers_top", "Vers Top"),
    ("versatile","Versatile"),
    ("vers_bot", "Vers Bottom"),
    ("bottom",   "Bottom"),
]

# ─────────────────────────────────────
# SUBSCRIPTION PLANS  (Razorpay)
# ─────────────────────────────────────
# ✅ Prices in whole rupees — converted to paise (x100) wherever Razorpay
# needs an amount. Change prices/durations here only; everything else
# (order creation, plan listing API, Flutter screen) reads from this.

PLAN_CHOICES = [
    ("week",         "1 Week"),
    ("month",        "1 Month"),
    ("three_months", "3 Months"),
]

PLAN_CONFIG = {
    "week":         {"label": "1 Week",  "price_inr": 49,  "duration_days": 7,  "tag": None},
    "month":        {"label": "1 Month", "price_inr": 99,  "duration_days": 30, "tag": "MOST POPULAR"},
    "three_months": {"label": "3 Months","price_inr": 199, "duration_days": 90, "tag": "BEST VALUE"},
}

PLAN_FEATURES = [
    "Unlimited Chats",
    "See Who Likes You",
    "Profile Boost",
    "Ad-Free Experience",
]

FREE_TRIAL_DAYS = 1


class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError("Phone number required")
        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone      = models.CharField(max_length=100, unique=True)   # stores email for email-OTP users
    is_active  = models.BooleanField(default=True)
    is_staff   = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD  = "phone"
    REQUIRED_FIELDS = []
    objects         = UserManager()

    def __str__(self):
        return self.phone

    # ✅ Premium status — computed from the latest *paid* subscription
    # that hasn't expired yet. No denormalized boolean to keep in sync;
    # single indexed query (see Subscription.Meta.indexes).
    @property
    def active_subscription(self):
        return (
            self.subscriptions
            .filter(status="paid", expires_at__gt=timezone.now())
            .order_by("-expires_at")
            .first()
        )

    @property
    def is_premium(self):
        return self.active_subscription is not None


# ─────────────────────────────────────
# EMAIL OTP  (replaces Firebase auth)
# ─────────────────────────────────────

class EmailOTP(models.Model):
    """
    Stores a 6-digit OTP for a given email address.
    - expires_at: 10 minutes from creation
    - is_used: True once verified (prevent reuse)
    """
    email      = models.EmailField()
    otp        = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used    = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes  = [models.Index(fields=["email", "otp"])]

    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    def __str__(self):
        return f"{self.email} — {self.otp} ({'used' if self.is_used else 'active'})"


# ─────────────────────────────────────
# PROFILE
# ─────────────────────────────────────

class Profile(models.Model):
    GENDER_CHOICES = [
        ("M", "Male"),
        ("F", "Female"),
        ("O", "Other"),
    ]

    user        = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    name        = models.CharField(max_length=50)
    bio         = models.TextField(max_length=300, blank=True)
    age         = models.PositiveSmallIntegerField(null=True, blank=True)
    gender      = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    photo_url   = models.URLField(max_length=500, blank=True, null=True)
    interests   = models.JSONField(default=list, blank=True)

    position    = models.CharField(
        max_length=10, choices=POSITION_CHOICES,
        blank=True, null=True,
    )
    has_room    = models.BooleanField(null=True, blank=True)

    latitude    = models.FloatField(null=True, blank=True, db_index=True)
    longitude   = models.FloatField(null=True, blank=True, db_index=True)
    is_complete = models.BooleanField(default=False)
    is_live     = models.BooleanField(default=False, db_index=True)
    live_since  = models.DateTimeField(null=True, blank=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        # ✅ "nearby" query hamesha is_live=True + lat/lng range filter karta
        # hai — composite index se ye query kaafi fast ho jaati hai.
        indexes = [
            models.Index(fields=["is_live", "latitude", "longitude"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.user.phone})"

    def go_live(self):
        self.is_live    = True
        self.live_since = timezone.now()
        self.save(update_fields=["is_live", "live_since"])

    def go_offline(self):
        self.is_live    = False
        self.live_since = None
        self.save(update_fields=["is_live", "live_since"])

    def common_interests(self, other_profile):
        return list(set(self.interests) & set(other_profile.interests))

    def interest_score(self, other_profile):
        if not self.interests or not other_profile.interests:
            return 0
        common = len(self.common_interests(other_profile))
        total  = len(set(self.interests) | set(other_profile.interests))
        return round((common / total) * 100) if total > 0 else 0


class Like(models.Model):
    sender     = models.ForeignKey(User, on_delete=models.CASCADE, related_name="likes_sent")
    receiver   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="likes_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("sender", "receiver")


class Match(models.Model):
    user1      = models.ForeignKey(User, on_delete=models.CASCADE, related_name="matches_as_user1")
    user2      = models.ForeignKey(User, on_delete=models.CASCADE, related_name="matches_as_user2")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        unique_together = ("user1", "user2")
        indexes = [models.Index(fields=["-created_at"])]


class Conversation(models.Model):
    match      = models.OneToOneField(Match, on_delete=models.CASCADE, related_name="conversation")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["-created_at"])]


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="messages_sent")
    text         = models.TextField()
    is_read      = models.BooleanField(default=False)
    created_at   = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        # ✅ "last message per conversation" subquery ab isi index ko use
        # karegi — bina index ke ye badi tables pe slow ho jaata.
        indexes = [models.Index(fields=["conversation", "-created_at"])]


class Block(models.Model):
    blocker    = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blocked_users")
    blocked    = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blocked_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("blocker", "blocked")


class Report(models.Model):
    REASON_CHOICES = [
        ("spam",       "Spam"),
        ("fake",       "Fake Profile"),
        ("harassment", "Harassment"),
        ("other",      "Other"),
    ]
    reporter    = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reports_made")
    reported    = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reports_received")
    reason      = models.CharField(max_length=20, choices=REASON_CHOICES)
    description = models.TextField(max_length=500, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)


# ─────────────────────────────────────
# SUBSCRIPTION  (Razorpay)
# ─────────────────────────────────────

class Subscription(models.Model):
    """
    Ek row = ek Razorpay order attempt.
    - created  : order Razorpay pe ban gaya, payment pending hai
    - paid     : signature verify ho gayi, subscription active hai
    - failed   : payment fail hua ya signature verify nahi hui
    - cancelled: order abandon ho gaya (app close, user ne cancel kiya)
    """
    STATUS_CHOICES = [
        ("created",   "Created"),
        ("paid",      "Paid"),
        ("failed",    "Failed"),
        ("cancelled", "Cancelled"),
    ]

    user     = models.ForeignKey(User, on_delete=models.CASCADE, related_name="subscriptions")
    plan     = models.CharField(max_length=20, choices=PLAN_CHOICES)
    amount   = models.PositiveIntegerField()             # paise
    currency = models.CharField(max_length=10, default="INR")

    razorpay_order_id   = models.CharField(max_length=100, unique=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature  = models.CharField(max_length=255, blank=True, null=True)

    status   = models.CharField(max_length=10, choices=STATUS_CHOICES, default="created", db_index=True)
    is_trial = models.BooleanField(default=False)   # ✅ free 1-day trial, ₹0, no Razorpay order

    starts_at  = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        # ✅ "user ka latest paid, unexpired subscription" query isi index
        # se serve hoti hai — is_premium check har request pe chal sakta hai.
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self):
        return f"{self.user.phone} — {self.plan} ({self.status})"

    def mark_paid(self, payment_id, signature):
        """
        Signature verify ho chuki hai — ab subscription activate karo.
        Agar user ka koi purana paid plan abhi bhi active hai, naya plan
        uski expiry ke baad se STACK hota hai (jaldi renew karne pe din
        waste nahi hote). Warna abhi se start hota hai.
        """
        now = timezone.now()
        existing = (
            Subscription.objects
            .filter(user=self.user, status="paid", expires_at__gt=now)
            .exclude(id=self.id)
            .order_by("-expires_at")
            .first()
        )
        start    = existing.expires_at if existing else now
        duration = timedelta(days=PLAN_CONFIG[self.plan]["duration_days"])

        self.razorpay_payment_id = payment_id
        self.razorpay_signature  = signature
        self.status     = "paid"
        self.starts_at  = start
        self.expires_at = start + duration
        self.save(update_fields=[
            "razorpay_payment_id", "razorpay_signature",
            "status", "starts_at", "expires_at", "updated_at",
        ])