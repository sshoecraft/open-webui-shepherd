# Authentication Router (`auths.py`)

## Architecture

The authentication system uses **username + password** for login (not email).

### Key Components

- **SigninForm**: `{username, password}` — accepts username for login
- **SignupForm**: `{name, username, email, password}` — username and email both required
- **AddUserForm**: extends SignupForm with `role` field

### Authentication Flow

1. **Signin**: Username looked up via `Users.get_user_by_username()`, password verified against bcrypt hash in `auth` table
2. **Signup**: Username validated (3-50 chars, alphanumeric + `._-`), uniqueness checked, email required and validated
3. **JWT**: Token created with `{id: user.id}` payload, stored in HttpOnly cookie + returned in response
4. **Trusted Header**: Auto-creates users from `WEBUI_AUTH_TRUSTED_EMAIL_HEADER`, deriving username from email
5. **LDAP**: Uses LDAP username directly as the Open WebUI username

### Database Tables

- **auth**: `{id, email, password, active}` — credentials storage
- **user**: `{id, email, username, role, name, ...}` — profile storage

### User ID in API Requests

The `user` field in OpenAI API chat completion requests sends `user.email` for non-pipeline models, and a full user object `{name, id, email, role}` for pipeline models.

### History

- **v0.8.1-shepherd.1**: Email made required again on signup. OpenAI API requests send user email instead of display name.
- **v0.8.0-shepherd.1**: Switched from email-based to username-based authentication. Username field added to all user forms.
- **v0.7.2-shepherd.1**: Added user ID (UUID) to OpenAI API chat completion requests.
