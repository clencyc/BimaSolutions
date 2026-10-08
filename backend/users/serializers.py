from django.contrib.auth import get_user_model
from rest_framework import serializers


User = get_user_model()
class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    class Meta:
        model = User
        fields = '__all__'

    
    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


