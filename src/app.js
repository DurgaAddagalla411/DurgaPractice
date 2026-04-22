// ============================================================
// SAMPLE APPLICATION — This is the "target" codebase that our
// GitHub Agents will work on. It's a simple Express-like API
// server with intentional areas for improvement, so the agents
// have realistic code to fix, review, and enhance.
// ============================================================

import http from "node:http";

// -----------------------------------------------------------
// In-memory "database" — a simple array of user objects.
// In production you'd use a real database, but this keeps our
// demo self-contained with no external dependencies.
// -----------------------------------------------------------
const users = [
  { id: 1, name: "Alice", email: "alice@example.com", role: "admin" },
  { id: 2, name: "Bob", email: "bob@example.com", role: "user" },
  { id: 3, name: "Charlie", email: "charlie@example.com", role: "user" },
];

// -----------------------------------------------------------
// Simple router — maps "METHOD /path" to handler functions.
// This avoids pulling in Express just for a demo.
// -----------------------------------------------------------
const routes = {};

function addRoute(method, path, handler) {
  routes[`${method.toUpperCase()} ${path}`] = handler;
}

// -----------------------------------------------------------
// ROUTE: GET /users — Return all users
// -----------------------------------------------------------
addRoute("GET", "/users", (req, res) => {
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ success: true, data: users }));
});

// -----------------------------------------------------------
// ROUTE: GET /users/:id — Return a single user by ID
// (fixed bug: return 404 error when user not found)
// -----------------------------------------------------------
addRoute("GET", "/users/:id", (req, res) => {
  const id = parseInt(req.params.id);
  const user = users.find((u) => u.id === id);
  if (!user) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ success: false, error: "User not found" }));
    return;
  }
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ success: true, data: user }));
});

// -----------------------------------------------------------
// ROUTE: GET /users/count — Return the total number of users
// -----------------------------------------------------------
addRoute("GET", "/users/count", (req, res) => {
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ success: true, count: users.length }));
});

// ... rest of the code remains the same ...
