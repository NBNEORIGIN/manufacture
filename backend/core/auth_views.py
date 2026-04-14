from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    email = request.data.get('email', '').strip().lower()
    password = request.data.get('password', '')

    if not email or not password:
        return Response({'error': 'Email and password required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

    user = authenticate(request, username=user.username, password=password)
    if not user:
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

    login(request, user)
    return Response({
        'user': {
            'id': user.id,
            'email': user.email,
            'name': user.get_full_name() or user.username,
            'is_staff': user.is_staff,
        }
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    logout(request)
    return Response({'message': 'Logged out'})


def _display_name(user):
    """
    Ivan review #10: show email prefix only for @nbnesigns.com users.
    'ivan@nbnesigns.com' -> 'ivan'. Falls back to full name or username.
    """
    if user.email and '@nbnesigns.com' in user.email:
        return user.email.split('@')[0]
    return user.get_full_name() or user.username


@api_view(['GET'])
@permission_classes([AllowAny])
def me_view(request):
    if not request.user.is_authenticated:
        return Response({'authenticated': False}, status=status.HTTP_401_UNAUTHORIZED)
    return Response({
        'authenticated': True,
        'user': {
            'id': request.user.id,
            'email': request.user.email,
            'name': _display_name(request.user),
            'is_staff': request.user.is_staff,
        }
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def users_list_view(request):
    """
    List all active users for dropdowns (Ivan review #10, item 3).
    Returns id + display_name (email prefix for @nbnesigns.com).
    """
    users = User.objects.filter(is_active=True).order_by('email', 'username')
    return Response({
        'users': [
            {
                'id': u.id,
                'display_name': _display_name(u),
                'email': u.email,
            }
            for u in users
        ]
    })
