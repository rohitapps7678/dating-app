from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Admin panel
    path("admin/", admin.site.urls),
    path("api/admin/", include("api.admin_urls")),

    # API routes
    path("api/", include("api.urls")),
]

# Development mein media files serve karo
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)