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
// (intentional bug: no 404 handling when user not found)
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
// ROUTE: POST /users — Create a new user
// (intentional gap: no input validation)
// -----------------------------------------------------------
addRoute("POST", "/users", (req, res) => {
  let body = "";
  req.on("data", (chunk) => (body += chunk));
  req.on("end", () => {
    const newUser = JSON.parse(body);
    // GAP: No validation — name, email, role could be missing
    newUser.id = users.length + 1;
    users.push(newUser);
    res.writeHead(201, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ success: true, data: newUser }));
  });
});

// -----------------------------------------------------------
// ROUTE: PUT /users/:id — Update a user by ID
// -----------------------------------------------------------
addRoute("PUT", "/users/:id", (req, res) => {
  const id = parseInt(req.params.id);
  const user = users.find((u) => u.id === id);
  if (!user) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ success: false, error: "User not found" }));
    return;
  }
  let body = "";
  req.on("data", (chunk) => (body += chunk));
  req.on("end", () => {
    const updates = JSON.parse(body);
    if (!updates.name && !updates.email && !updates.role) {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ success: false, error: "No valid fields provided" }));
      return;
    }
    if (updates.name) user.name = updates.name;
    if (updates.email) user.email = updates.email;
    if (updates.role) user.role = updates.role;
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ success: true, data: user }));
  });
});

// -----------------------------------------------------------
// ROUTE: DELETE /users/:id — Delete a user by ID
// -----------------------------------------------------------
addRoute("DELETE", "/users/:id", (req, res) => {
  const id = parseInt(req.params.id);
  const index = users.findIndex((u) => u.id === id);
  if (index === -1) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ success: false, error: "User not found" }));
    return;
  }
  users.splice(index, 1);
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ success: true, message: "User deleted" }));
});

// -----------------------------------------------------------
// ROUTE: GET /health — Health check endpoint
// -----------------------------------------------------------
addRoute("GET", "/health", (req, res) => {
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ status: "ok", uptime: process.uptime() }));
});

// -----------------------------------------------------------
// HTTP Server — matches incoming requests against our routes.
// Supports simple path parameters like /users/:id.
// -----------------------------------------------------------
const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const method = req.method.toUpperCase();
  const path = url.pathname;

  // Try exact match first
  const exactKey = `${method} ${path}`;
  if (routes[exactKey]) {
    req.params = {};
    return routes[exactKey](req, res);
  }

  // Try parameterized routes (e.g., /users/:id)
  for (const [routeKey, handler] of Object.entries(routes)) {
    const [routeMethod, routePath] = routeKey.split(" ");
    if (routeMethod !== method) continue;

    const routeParts = routePath.split("/");
    const pathParts = path.split("/");

    if (routeParts.length !== pathParts.length) continue;

    const params = {};
    let match = true;

    for (let i = 0; i < routeParts.length; i++) {
      if (routeParts[i].startsWith(":")) {
        params[routeParts[i].slice(1)] = pathParts[i];
      } else if (routeParts[i] !== pathParts[i]) {
        match = false;
        break;
      }
    }

    if (match) {
      req.params = params;
      return handler(req, res);
    }
  }

  // No route matched — return 404
  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ success: false, error: "Route not found" }));
});

// -----------------------------------------------------------
// Start the server
// -----------------------------------------------------------
const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
  console.log("Available routes:");
  console.log("  GET    /health");
  console.log("  GET    /users");
  console.log("  GET    /users/:id");
  console.log("  POST   /users");
  console.log("  PUT    /users/:id");
  console.log("  DELETE /users/:id");
});

export default server;
