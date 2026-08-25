<?php
require_once __DIR__ . '/db.php';
header('Content-Type: application/json');

$token = $_COOKIE['moya_token'] ?? '';
if ($token) {
    $stmt = db()->prepare("DELETE FROM sessions WHERE token = ?");
    $stmt->execute([$token]);
}
setcookie('moya_token', '', time() - 3600, '/', '', true, true);
echo json_encode(['ok' => true, 'message' => 'Logged out']);
