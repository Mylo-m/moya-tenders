<?php
/**
 * Moya — Complete Application
 * User auth + Tender Dashboard + API
 */

define('DB_PATH', __DIR__ . '/moya.db');

/**
 * Lightweight rate limiter for public tender APIs.
 * Caps per-IP requests to keep the sovereign DB cheap to serve.
 * Returns true if the request is allowed.
 */
function rate_limit($key, $max = 60, $window = 60) {
    $store = sys_get_temp_dir() . '/moya_rl_' . md5($key);
    $now = time();
    $hits = [];
    if (file_exists($store)) {
        $hits = @json_decode(file_get_contents($store), true) ?: [];
    }
    $hits = array_filter($hits, fn($t) => $t > ($now - $window));
    if (count($hits) >= $max) {
        return false;
    }
    $hits[] = $now;
    @file_put_contents($store, json_encode($hits));
    return true;
}

function db() {
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO('sqlite:' . DB_PATH);
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
    }
    return $pdo;
}

function init_db() {
    $db = db();
    
    $db->exec("
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            sector TEXT DEFAULT '',
            sectors TEXT DEFAULT '',
            base_sector TEXT DEFAULT '',
            extra_sectors TEXT DEFAULT '',
            monthly_extra_fee INTEGER DEFAULT 0,
            company TEXT DEFAULT '',
            tier TEXT DEFAULT 'free',
            created_at TEXT DEFAULT (datetime('now')),
            last_login TEXT
        )
    ");
    
    $db->exec("
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ");
    
    $db->exec("
        CREATE TABLE IF NOT EXISTS tenders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_key TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            issuing_dept TEXT,
            sector TEXT,
            province TEXT,
            advert_date TEXT,
            closing_date TEXT,
            status TEXT DEFAULT 'open',
            contact_person TEXT,
            contact_email TEXT,
            contact_phone TEXT,
            document_url TEXT,
            source_url TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    ");
    
    $db->exec("CREATE INDEX IF NOT EXISTS idx_tenders_sector ON tenders(sector)");
    $db->exec("CREATE INDEX IF NOT EXISTS idx_tenders_province ON tenders(province)");
    $db->exec("CREATE INDEX IF NOT EXISTS idx_tenders_closing ON tenders(closing_date)");
    $db->exec("CREATE INDEX IF NOT EXISTS idx_tenders_status ON tenders(status)");
}

init_db();

// Migration: ensure the sector-scoping columns exist on existing installs.
// (init_db uses CREATE TABLE IF NOT EXISTS, so already-created tables keep their old shape.)
$db = db();
$cols = [];
try {
    $res = $db->query("PRAGMA table_info(users)");
    while ($row = $res->fetch()) { $cols[] = $row['name']; }
} catch (Exception $e) { $cols = []; }
$addCols = [
    'sectors' => "TEXT DEFAULT ''",
    'base_sector' => "TEXT DEFAULT ''",
    'extra_sectors' => "TEXT DEFAULT ''",
    'monthly_extra_fee' => 'INTEGER DEFAULT 0',
    'phone' => "TEXT DEFAULT ''",
    'plan' => "TEXT DEFAULT ''",
    'moya_token' => "TEXT DEFAULT ''",
    'ai_module' => 'INTEGER DEFAULT 0',
    'payment_status' => "TEXT DEFAULT 'free'",
    'paid_until' => "TEXT DEFAULT ''",
    'payfast_txn' => "TEXT DEFAULT ''",
    'founded_plan' => "TEXT DEFAULT ''",
    'founded_at' => "TEXT DEFAULT ''",
    'country_code' => "TEXT DEFAULT ''",
    'consent' => "TEXT DEFAULT ''",
];
foreach ($addCols as $col => $def) {
    if (!in_array($col, $cols, true)) {
        try { $db->exec("ALTER TABLE users ADD COLUMN $col $def"); } catch (Exception $e) {}
    }
}

// Migrate the tenders table to multi-country shape (idempotent).
$tcols = [];
try {
    $res = $db->query("PRAGMA table_info(tenders)");
    while ($row = $res->fetch()) { $tcols[] = $row['name']; }
} catch (Exception $e) { $tcols = []; }
$tAdd = [
    'country' => "TEXT DEFAULT ''",
    'country_code' => "TEXT DEFAULT ''",
    'region' => "TEXT DEFAULT ''",
    'contact_person' => "TEXT DEFAULT ''",
    'contact_email' => "TEXT DEFAULT ''",
    'contact_phone' => "TEXT DEFAULT ''",
    'document_url' => "TEXT DEFAULT ''",
];
foreach ($tAdd as $col => $def) {
    if (!in_array($col, $tcols, true)) {
        try { $db->exec("ALTER TABLE tenders ADD COLUMN $col $def"); } catch (Exception $e) {}
    }
}
// Backfill legacy rows lacking a country.
try { $db->exec("UPDATE tenders SET country='South Africa', country_code='ZA', region='Southern Africa' WHERE country IS NULL OR country=''"); } catch (Exception $e) {}

// R500 per extra sector, per month (over and above the base signup sector)
define('EXTRA_SECTOR_FEE', 500);
// R1290 per month for the AI & Intelligence module (automation, private
// project tracking, document-parsing engine). Billed as a monthly add-on.
define('AI_MODULE_FEE', 1290);

/**
 * Is the AI & Intelligence module currently active for this user?
 * Requires the add-on to be selected AND a non-expired paid period.
 */
function aiModuleActive($user) {
    if (empty($user['ai_module'])) return false;
    if (empty($user['paid_until'])) return false;
    $ts = strtotime($user['paid_until']);
    return $ts !== false && $ts > time();
}

/**
 * AI FEATURE WIRING POINT (PromptFoo-style hardening, pre-wired 2026-08-23).
 * When you build the RFP/BOQ parser, private project tracking, or any AI feature
 * for the AI & Intelligence module, route ALL model calls through
 *   require_once __DIR__ . '/moya_ai.php';  mylo_moya_llm_chat($system, $user, $opts)
 * That helper injects the instruction guard (F2), fences untrusted user input (F1),
 * and sanitises output (F4) — so the feature is safe by default. Do NOT call an LLM
 * directly from Moya code; use mylo_moya_llm_chat().
 */

/**
 * Resolve the full list of sectors a user is allowed to see.
 * Base sector (free, always) + any paid extra_sectors (only while paid).
 */
function isFoundingLifetime($user) {
    return ($user['payment_status'] ?? '') === 'founding_lifetime';
}

/**
 * Resolve the full list of sectors a user is allowed to see.
 * Base sector (free, always) + any paid extra_sectors (only while paid).
 * Founding Lifetime members see EVERYTHING (empty allow-list = unrestricted
 * in getTenders), permanently — no monthly bills, no expiry.
 */
function allowedSectors($user) {
    // Founding Lifetime: unrestricted access to all sectors.
    if (isFoundingLifetime($user)) {
        return [];
    }
    $list = [];
    if (!empty($user['base_sector'])) $list[] = $user['base_sector'];
    if (aiModuleActive($user) && !empty($user['extra_sectors'])) {
        foreach (explode(',', $user['extra_sectors']) as $s) {
            $s = trim($s);
            if ($s) $list[] = $s;
        }
    }
    return array_values(array_unique($list));
}

/**
 * Compute a user's monthly plan total (extra sectors + AI module).
 * Used for display and as the authoritative bill — never reads the client.
 */
function monthlyPlanTotal($user) {
    $extra = (int)($user['monthly_extra_fee'] ?? 0);
    $ai = !empty($user['ai_module']) ? AI_MODULE_FEE : 0;
    return $extra + $ai;
}

// Total number of Founding Lifetime slots available (scarcity lever).
define('FOUNDING_SLOTS', 20);

/**
 * How many Founding slots have been claimed.
 * Counts any user who selected a Founding plan (pending payment or active).
 */
function foundingSlotsTaken() {
    try {
        return (int)db()->query("SELECT COUNT(*) FROM users WHERE founding_plan <> '' AND founding_plan IS NOT NULL")->fetchColumn();
    } catch (Exception $e) {
        return 0;
    }
}

/**
 * Email helper — mirrors orders.php: tries mail(), falls back to a log file.
 */
function moyaSendMail($to, $subject, $bodyHtml) {
    $headers = "From: MY-LO <noreply@mylo.co.za>\r\n";
    $headers .= "Reply-To: sales@mylo.co.za\r\n";
    $headers .= "MIME-Version: 1.0\r\n";
    $headers .= "Content-Type: text/html; charset=UTF-8\r\n";
    $sent = @mail($to, $subject, $bodyHtml, $headers);
    if (!$sent) {
        @file_put_contents(__DIR__ . '/mail_log.txt', date('c') . " | TO: $to | $subject\n", FILE_APPEND | LOCK_EX);
    }
    return $sent;
}

/**
 * On Founding-plan signup: email the customer a reservation confirmation
 * and notify the MY-LO sales desk. Safe to call even if mail() is unavailable.
 */
function sendFoundingSelectEmails($name, $email, $planKey) {
    $labels = [
        'ict_pro'       => 'ICT Core Pro — Founding Lifetime (R2,499 once-off)',
        'enterprise_ai' => 'Enterprise AI & Intelligence — Founding Lifetime (R4,999 once-off)',
    ];
    $planLabel = $labels[$planKey] ?? $planKey;
    $name = htmlspecialchars($name ?: 'there');

    $cust = "
    <div style='font-family:Inter,Arial,sans-serif;background:#f6f7f9;padding:40px 20px'>
      <div style='max-width:600px;margin:0 auto;background:#fff;border-radius:16px;padding:40px;border:1px solid #e5e7eb'>
        <h1 style='font-size:1.4rem;color:#7170ff;margin:0'>MY-LO · Moya</h1>
        <p style='color:#16181d;font-size:1rem;line-height:1.6'>Hi $name,</p>
        <p style='color:#5b606b;font-size:.95rem;line-height:1.6'>Your <strong>Founding Member</strong> slot is reserved. You selected the <strong>$planLabel</strong> Lifetime Pass.</p>
        <p style='color:#5b606b;font-size:.95rem;line-height:1.6'>Complete your one-time payment on the next screen to permanently unlock every sector + the AI &amp; Intelligence module — no monthly bills, ever.</p>
        <p style='color:#8a8f98;font-size:.8rem'>If you didn't start this signup, you can ignore this email — no charge has been made.</p>
      </div>
    </div>";

    $admin = "
    <div style='font-family:Inter,Arial,sans-serif;padding:20px'>
      <h2 style='color:#7170ff'>New Founding Pass selection</h2>
      <p><strong>Name:</strong> " . htmlspecialchars($name) . "<br>
         <strong>Email:</strong> $email<br>
         <strong>Plan:</strong> $planLabel</p>
      <p>Payment pending via PayFast (one-time).</p>
    </div>";

    moyaSendMail($email, 'Your Moya Founding Pass is reserved', $cust);
    moyaSendMail('sales@mylo.co.za', 'New Founding Pass selection — ' . $email, $admin);
}


/**
 * Server-side monthly amount owed for the current saved selection.
 * This is the figure the PayFast checkout bills and the ITN must match.
 */
function moyaMonthlyOwed($user) {
    return monthlyPlanTotal($user);
}

function registerUser($name, $email, $password, $sector = '', $company = '', $phone = '', $extra = [], $consent = '') {
    $hash = password_hash($password, PASSWORD_DEFAULT);
    $extraStr = implode(',', array_filter(array_map('trim', $extra)));
    $extraFee = count(array_filter(array_map('trim', $extra))) * EXTRA_SECTOR_FEE;
    // The chosen sector at signup is their single FREE base sector.
    $stmt = db()->prepare("INSERT INTO users (name, email, password_hash, sector, base_sector, sectors, company, phone, extra_sectors, monthly_extra_fee, consent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)");
    $stmt->execute([$name, $email, $hash, $sector, $sector, $sector, $company, $phone, $extraStr, $extraFee, $consent ? date('c') : '']);
    return db()->lastInsertId();
}

function loginUser($email, $password) {
    $stmt = db()->prepare("SELECT * FROM users WHERE email = ?");
    $stmt->execute([$email]);
    $user = $stmt->fetch();
    if ($user && password_verify($password, $user['password_hash'])) {
        db()->prepare("UPDATE users SET last_login = datetime('now') WHERE id = ?")->execute([$user['id']]);
        $token = bin2hex(random_bytes(32));
        db()->prepare("INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, datetime('now', '+30 days'))")->execute([$token, $user['id']]);
        setcookie('tm_token', $token, time() + 86400 * 30, '/', '', true, true);
        $allowed = allowedSectors($user);
        return ['ok' => true, 'token' => $token, 'user' => [
            'id' => $user['id'], 'name' => $user['name'], 'email' => $user['email'],
            'sector' => $user['sector'], 'base_sector' => $user['base_sector'],
            'extra_sectors' => $user['extra_sectors'], 'company' => $user['company'],
            'allowed_sectors' => $allowed, 'monthly_extra_fee' => (int)($user['monthly_extra_fee'] ?? 0),
        ]];
    }
    return ['ok' => false, 'error' => 'Invalid email or password'];
}

function getCurrentUser() {
    $token = $_COOKIE['tm_token'] ?? '';
    if (!$token) return null;
    $stmt = db()->prepare("SELECT u.* FROM users u JOIN sessions s ON u.id = s.user_id WHERE s.token = ? AND s.expires_at > datetime('now')");
    $stmt->execute([$token]);
    $user = $stmt->fetch();
    if ($user) $user['allowed_sectors'] = allowedSectors($user);
    return $user;
}

function getTenders($filters = [], $limit = 50, $offset = 0, $allowed = null) {
    $where = ["1=1"];
    $params = [];

    // Strict sector scoping: a logged-in user only sees their allowed sectors.
    // 'other' / empty means unrestricted (see everything) — do NOT scope to a literal 'other' sector.
    if (is_array($allowed) && count($allowed) > 0) {
        $real = array_filter($allowed, function($s){ return $s !== 'other' && $s !== '' && $s !== null; });
        if (count($real) > 0) {
            $ph = implode(',', array_fill(0, count($real), '?'));
            $where[] = "sector IN ($ph)";
            $params = array_merge($params, array_values($real));
        }
        // if only 'other'/empty sectors, leave unrestricted (no sector clause)
    }

    if (!empty($filters['province'])) {
        $where[] = "province LIKE ?";
        $params[] = "%{$filters['province']}%";
    }
    if (!empty($filters['sector'])) {
        // Dropdown sector filter applies for ALL users (guest or logged-in).
        $where[] = "sector = ?";
        $params[] = $filters['sector'];
    }
    if (!empty($filters['status'])) {
        $where[] = "status = ?";
        $params[] = $filters['status'];
    }
    if (!empty($filters['country'])) {
        $where[] = "country_code = ?";
        $params[] = $filters['country'];
    }
    if (!empty($filters['search'])) {
        $where[] = "(title LIKE ? OR description LIKE ? OR issuing_dept LIKE ?)";
        $params[] = "%{$filters['search']}%";
        $params[] = "%{$filters['search']}%";
        $params[] = "%{$filters['search']}%";
    }

    $where_sql = implode(" AND ", $where);

    $count_stmt = db()->prepare("SELECT COUNT(*) FROM tenders WHERE $where_sql");
    $count_stmt->execute($params);
    $total = $count_stmt->fetchColumn();

    $stmt = db()->prepare("SELECT * FROM tenders WHERE $where_sql ORDER BY closing_date ASC, created_at DESC LIMIT ? OFFSET ?");
    $stmt->execute(array_merge($params, [$limit, $offset]));
    $tenders = $stmt->fetchAll();

    return ['total' => $total, 'tenders' => $tenders];
}

function addTender($data) {
    $source_key = hash('sha256', ($data['source'] ?? '') . ($data['source_url'] ?? ''));
    $stmt = db()->prepare("
        INSERT OR IGNORE INTO tenders (source, source_key, title, description, issuing_dept, sector, province, advert_date, closing_date, status, source_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ");
    try {
        $stmt->execute([
            $data['source'],
            $source_key,
            $data['title'],
            $data['description'] ?? '',
            $data['issuing_dept'] ?? '',
            $data['sector'] ?? null,
            $data['province'] ?? '',
            $data['advert_date'] ?? null,
            $data['closing_date'] ?? null,
            $data['status'] ?? 'open',
            $data['source_url'] ?? ''
        ]);
        return db()->lastInsertId() ?: 0;
    } catch (Exception $e) {
        return 0;
    }
}

function getStats() {
    $total = db()->query("SELECT COUNT(*) FROM tenders")->fetchColumn();
    $open = db()->query("SELECT COUNT(*) FROM tenders WHERE status = 'open'")->fetchColumn();
    $today = db()->query("SELECT COUNT(*) FROM tenders WHERE date(created_at) = date('now')")->fetchColumn();
    $sectors = db()->query("SELECT sector, COUNT(*) as count FROM tenders WHERE sector IS NOT NULL GROUP BY sector ORDER BY count DESC LIMIT 5")->fetchAll();
    return ['total' => $total, 'open' => $open, 'today' => $today, 'top_sectors' => $sectors];
}

/**
 * Country badge (flag emoji + code) for tender cards.
 */
function countryBadge($cc) {
    $map = ['ZA' => '🇿🇦 South Africa', 'KE' => '🇰🇪 Kenya', 'NG' => '🇳🇬 Nigeria',
            'ET' => '🇪🇹 Ethiopia', 'UG' => '🇺🇬 Uganda', 'GH' => '🇬🇭 Ghana',
            'TZ' => '🇹🇿 Tanzania', 'ZM' => '🇿🇲 Zambia', 'MW' => '🇲🇼 Malawi',
            'RW' => '🇷🇼 Rwanda', 'MZ' => '🇲🇿 Mozambique'];
    return $map[$cc] ?? ($cc ?: '—');
}

/**
 * Compliance-aware eligibility for a logged-in client against a tender.
 * Returns ['eligible'=>bool,'reasons'=>[]]. Reads the client's supplier profile.
 *  - ZA construction tender + no CIDB grading -> not eligible (flag).
 *  - KE AGPO-only preference notice -> note if client holds AGPO.
 * This is advisory (the engine is an internal tracker), not a hard gate.
 */
function tenderEligibility($user, $tender) {
    if (!$user) return ['eligible' => true, 'reasons' => []];
    require_once __DIR__ . '/compliance_lib.php';
    $cc = $tender['country_code'] ?? '';
    if ($cc !== ($user['country_code'] ?? '')) {
        return ['eligible' => false, 'reasons' => ['Tender is in ' . countryBadge($cc) . '; your profile is set to ' . countryBadge($user['country_code'] ?? '') . '.']];
    }
    $sup = null;
    try { $sup = c_get_or_create_supplier($user['id'], $cc); } catch (Exception $e) { return ['eligible' => true, 'reasons' => []]; }
    $reasons = [];
    if (($tender['sector'] ?? '') === 'construction' && $cc === 'ZA') {
        $cidb = cdb()->query("SELECT cert_level FROM certificates WHERE supplier_id={$sup['id']} AND cert_key='cidb'")->fetchColumn();
        if (!$cidb) $reasons[] = 'Construction bid — you have no CIDB grading on file (required to submit).';
    }
    return ['eligible' => count($reasons) === 0, 'reasons' => $reasons];
}
