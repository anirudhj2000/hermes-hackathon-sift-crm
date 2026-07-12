from rest_framework.routers import DefaultRouter

from .views import (
    ConnectionViewSet,
    ContactViewSet,
    InteractionViewSet,
    WorkflowRunViewSet,
    WorkflowViewSet,
)

router = DefaultRouter()
router.register(r"contacts", ContactViewSet, basename="contact")
router.register(r"interactions", InteractionViewSet, basename="interaction")
router.register(r"workflows", WorkflowViewSet, basename="workflow")
router.register(r"runs", WorkflowRunViewSet, basename="run")
router.register(r"connections", ConnectionViewSet, basename="connection")

urlpatterns = router.urls
