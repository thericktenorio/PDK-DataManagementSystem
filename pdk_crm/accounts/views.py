from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.contrib.auth import login, logout
from .serializers import LoginSerializer, InternalUserSerializer


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data = request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            login(request, user)
            return Response(InternalUserSerializer(user).data)
        return Response(serializer.error, status = status.HTTP_400_BAD_REQUEST)


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response({"detail": "Logged out."}, status = status.HTTP_200_OK)