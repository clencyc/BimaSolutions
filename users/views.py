from django.shortcuts import render
from django.shortcuts import render
from django.contrib.auth import authenticate
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .serializers import UserCreateSerializer


# Create your views here.


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    username = request.data.get("username")
    password = request.data.get("password")

    if not username or not password:
        return Response(
            {
                "detail": "username and password are required"
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response(
            {
                "detail": "invalid credentials"
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )
    refresh = RefreshToken.for_user(user)

    return Response(
        {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": {
                "id": user.id,
                "username": user.get_username(),
                "email": getattr(user, "email", None),
                "role_name": getattr(user, "role_name", "")
            },
        }
    )



@api_view(["POST"])
@permission_classes([IsAdminUser])
def create_user(request):
    serializer = UserCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    return Response(
        {
            "id": user.id,
            "username": user.get_username(),
            "email": getattr(user, "email", ""),
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    refresh_token = request.data.get("refresh")
    if not refresh_token:
        return Response(
            {"detail": "Refresh token is required"}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
    except TokenError:
        return Response(
            {"detail": "Invalid refresh token"}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    return Response({
        "detail": "logged out"
    },
    status=status.HTTP_200_OK
    )
# @api_view(['POST'])
# def logout(request):
#     request.user.auth_token.delete()
#     return Response({"detail": "logged out"})

