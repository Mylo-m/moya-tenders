<?php
/**
 * MY-LO Tools — Login
 */

require_once __DIR__ . '/db.php';

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
if ($_SERVER['REQUEST_METHOD'] !== 'POST') { http_response_code(405); echo json_encode(['ok'=>false,'error'=>'Method not allowed']); exit; }

$ct = $_SERVER['CONTENT_TYPE'] ?? '';
$input = (stripos($ct, 'application/json') !== false) ? (json_decode(file_get_contents('php://input'), true) ?: []) : $_POST;

$email = trim(strtolower($input['email'] ?? ''));
$password = $input['password'] ?? '';

if (!$email || !$password) {
    http_response_code(422);
    echo json_encode(['ok'=>false,'error'=>'Email and password are required.']);
    exit;
}

$stmt = db()->prepare("SELECT * FROM users WHERE email = ?");
$stmt->execute([$email]);
$user = $stmt->fetch();

if (!$user || !password_verify($password, $user['password_hash'])) {
    http_response_code(401);
    echo json_encode(['ok'=>false,'error'=>'Invalid email or password.']);
    exit;
}

// Update last login
$stmt = db()->prepare("UPDATE users SET last_login = datetime('now') WHERE id = ?");
$stmt->execute([$user['id']]);

// Create session
$token = bin2hex(random_bytes(32));
$expires = date('c', time() + 86400 * 30);
$stmt = db()->prepare("INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)");
$stmt->execute([$token, $user['id'], $expires]);

setcookie('moya_token', $token, time() + 86400 * 30, '/', '', true, true);

echo json_encode([
    'ok' => true,
    'message' => 'Welcome back!',
    'user' => ['id' => $user['id'], 'name' => $user['name'], 'surname' => $user['surname'], 'email' => $user['email'], 'phone' => $user['phone']],
    'token' => $token
]);
