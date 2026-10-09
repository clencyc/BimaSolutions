from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import MultipleObjectsReturned


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        email = kwargs.get("email", username)
        if (
            not isinstance(email, str)
            or not email.strip()
            or not isinstance(password, str)
            or not password
        ):
            return None

        user_model = get_user_model()
        try:
            user = user_model._default_manager.get(email__iexact=email.strip())
        except user_model.DoesNotExist:
            return super().authenticate(
                request,
                username=email.strip(),
                password=password,
            )
        except MultipleObjectsReturned:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
