from rest_framework import serializers

from .models import Connection, Contact, Interaction, Workflow, WorkflowRun


class InteractionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Interaction
        fields = [
            "id",
            "contact",
            "source",
            "external_id",
            "direction",
            "body",
            "ts",
            "extracted",
        ]


class ContactListSerializer(serializers.ModelSerializer):
    interaction_count = serializers.IntegerField(read_only=True)
    last_ts = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = Contact
        fields = [
            "id",
            "name",
            "phone",
            "email",
            "company",
            "tags",
            "created_at",
            "interaction_count",
            "last_ts",
        ]


class ContactDetailSerializer(serializers.ModelSerializer):
    interactions = serializers.SerializerMethodField()
    interaction_count = serializers.IntegerField(read_only=True)
    last_ts = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = Contact
        fields = [
            "id",
            "name",
            "phone",
            "email",
            "company",
            "tags",
            "created_at",
            "interaction_count",
            "last_ts",
            "interactions",
        ]

    def get_interactions(self, obj):
        qs = obj.interactions.order_by("-ts")
        return InteractionSerializer(qs, many=True).data


class ConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Connection
        fields = ["id", "source", "status", "meta"]


class WorkflowSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workflow
        fields = ["id", "name", "dsl", "created_by_chat_id", "created_at"]
        read_only_fields = ["created_by_chat_id"]


class WorkflowRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowRun
        fields = [
            "id",
            "workflow",
            "status",
            "stats",
            "log",
            "started_at",
            "finished_at",
        ]
