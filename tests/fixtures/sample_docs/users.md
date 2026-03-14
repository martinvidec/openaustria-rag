# User Management

The UserService is the central component for managing users in the system.
It provides methods for creating, reading, updating, and deleting user records.

## Getting Users

The `getUsers` method returns all users from the database. It is exposed
as a REST endpoint at `GET /users` and requires authentication.

## Creating Users

The `createUser` method takes a User object and persists it to the database.
Validation is performed before saving. The endpoint is `POST /users`.

## Configuration

User management can be configured via the application settings.
Default settings use an in-memory database for development.
