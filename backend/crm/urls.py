from rest_framework.routers import DefaultRouter

from .views import (
    ConnectionViewSet,
    TableViewSet,
    WorkflowRunViewSet,
    WorkflowViewSet,
)

router = DefaultRouter()
router.register(r"tables", TableViewSet, basename="table")
router.register(r"workflows", WorkflowViewSet, basename="workflow")
router.register(r"runs", WorkflowRunViewSet, basename="run")
router.register(r"connections", ConnectionViewSet, basename="connection")

urlpatterns = router.urls
