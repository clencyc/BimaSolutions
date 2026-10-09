from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class JwtAuthenticationTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="test-user",
            email="test@example.com",
            password="correct-horse-battery",
        )

    def login(self, email="test@example.com", password="correct-horse-battery"):
        return self.client.post(
            reverse("login"),
            {"email": email, "password": password},
            format="json",
        )

    def test_login_issues_tokens_for_email_and_password(self):
        response = self.login(email="TEST@example.com")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["user"]["id"], self.user.pk)

    def test_login_rejects_invalid_credentials(self):
        response = self.login(password="wrong-password")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_can_log_in_with_username(self):
        admin = get_user_model().objects.create_superuser(
            username="admin-user",
            email="admin@example.com",
            password="admin-password",
        )

        self.assertTrue(
            self.client.login(username=admin.username, password="admin-password")
        )

    def test_logout_requires_authentication_and_blacklists_refresh(self):
        tokens = self.login().data
        response = self.client.post(
            reverse("logout"),
            {"refresh": tokens["refresh"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        response = self.client.post(
            reverse("logout"),
            {"refresh": tokens["refresh"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_logout_rejects_another_users_refresh_token(self):
        other_user = get_user_model().objects.create_user(
            username="other-user",
            email="other@example.com",
            password="another-correct-password",
        )
        other_refresh = self.login(
            email=other_user.email,
            password="another-correct-password",
        ).data["refresh"]
        own_tokens = self.login().data
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {own_tokens['access']}")

        response = self.client.post(
            reverse("logout"),
            {"refresh": other_refresh},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
