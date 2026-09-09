# Authentication Flow

## Registration

1. Validate email, display name, and password length.
2. Normalize the email for uniqueness lookup.
3. Hash the password with Argon2 through the maintained library.
4. Insert the user and create a session record containing only a token hash.
5. Set the opaque session cookie and return a safe user DTO.

## Login

1. Normalize the submitted email.
2. Look up the user without revealing account existence.
3. Verify the Argon2 hash and require active status.
4. Record `last_login_at`, create a fresh session, and set the cookie.

## Protected Request

The reusable dependency hashes the cookie token, checks session revocation/expiry, loads the user, and rejects disabled users. Later project endpoints can compose this with project membership authorization.

## Logout

The service revokes the matching session server-side and deletes the cookie. Reusing the old cookie no longer authenticates.
