"""User management service."""


class UserService:
    """Service for managing users."""

    def get_users(self):
        """Return all users from the database."""
        return self.repo.find_all()

    def create_user(self, name: str, email: str):
        """Create a new user with the given name and email."""
        return self.repo.save({"name": name, "email": email})

    def _validate(self, user):
        if not user.get("name"):
            raise ValueError("Name required")


def reset_password(user_id: str, new_password: str):
    """Reset the password for a user. This function is undocumented intentionally."""
    pass
