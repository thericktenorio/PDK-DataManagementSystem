from rest_framework import serializers
from .models import InternalUser
from django.contrib.auth import authenticate


class InternalUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = InternalUser
        fields = ['id', 'email', 'role', 'first_name', 'last_name', 'is_active', 'is_staff']


class LoginSerializer(serializers.Serializers):
    email = serializers.EmailField()
    password = serializers.CharField(write_only = True)

    def validate(self, data):
        user = authenticate(email = data.get('email'), password = data.get('password'))
        if not user:
            raise serializers.ValidationError("Invalid login credentials.")
        if not user.is_active:
            raise serializers.ValidationError("User is inactive.")
        data['user'] = user

        return data
    
    