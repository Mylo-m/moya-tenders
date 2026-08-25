<?php
/**
 * Moya — ICT & AI Intelligence Command Center (dashboard.php)
 *
 * Focused portal for high-tech infrastructure contractors, systems
 * integrators and AI solution providers. Legacy construction / plumbing
 * noise is excluded — only the ICT + Pro AV technology pool is surfaced.
 *
 * The "Analyze with Moya AI" Shredder is powered by a real, offline
 * heuristic extraction engine (v1). It runs entirely server-side with
 * zero API cost. The llmAnalyzeTender() hook is provided so a live
 * LLM call (client-supplied key, billed direct) can replace the
 * heuristic later without touching the UI.
 */

require_once __DIR__ . '/moya.php';

// ---------------------------------------------------------------------------
// ICT / AI focus configuration
// ---------------------------------------------------------------------------

// The only sectors that belong in the Intelligence Hub. Anything else
// (construction, cleaning, agriculture, …) is legacy noise and is hidden.
$TECH_POOL = ['ict', 'audio_visual'];

// Soft gate: drop tech-pool rows that carry no actual ICT/AV signal at all
// (many 'ict'-tagged rows are mis-tagged non-tech noise). Set false to show
// every tech-pool row regardless of signal.
$HIDE_NOISE = true;

// Vertical switcher vectors. `key` maps to classifyVectors().
$VECTORS = [
    'all'      => ['label' => 'All Tech',           'icon' => 'fa-layer-group'],
    'pro_av'   => ['label' => 'Pro AV & Control',    'icon' => 'fa-tower-broadcast'],
    'itc'      => ['label' => 'ITC Networks',        'icon' => 'fa-network-wired'],
    'hardware' => ['label' => 'Hardware Supply',     'icon' => 'fa-microchip'],
    'si'       => ['label' => 'Turnkey SI',          'icon' => 'fa-screwdriver-wrench'],
    'ai'       => ['label' => 'Sovereign AI',        'icon' => 'fa-brain'],
];

/**
 * Keyword dictionaries used both for vector classification and for the
 * Shredder extraction. Order does not matter; matches are case-insensitive.
 */
$KW = [
    'pro_av' => ['audio visual','audio-visual','audiovisual','a/v','av equipment','q-sys','qsys','crestron','extron',
        'projector','video wall','video','led wall','led display','sound system','pa system',
        'public address','conferencing','zoom rooms','broadcast','av distribution','dsp',
        'mixing console','speaker','microphone','control room','matrix switcher',
        'signal distribution','digital signage','intercom','visualiser',
        'virtual reality',' vr ','creative cloud','photographic'],
    'itc' => ['network','fibre','fiber','local area',' lan','wan','router','switch',
        'cisco','juniper','aruba','structured cabling','cabling','sd-wan','wifi',
        'wireless','firewall','vpn','mpls','connectivity','vsat','microwave',
        'internet service','data centre','datacenter','ip telephony','voip',
        'optical fibre','leased line','core network'],
    'hardware' => ['hardware','server','endpoint','laptop','notebook','desktop','monitor',
        'thin client','workstation','printer','ups','storage array','computer',
        'supply of','supply and delivery','rfq','procurement of','lease of','cctv',
        'camera','access control','biometric','compute','rack','endpoints','switches'],
    'si' => ['turnkey','system integration','systems integration','implement',
        'implementation','deployment','roll out','rollout','installation','upgrade',
        'migration','managed service','maintenance','support','supply and install',
        'design and build','professional services','project management','solutions'],
    'ai' => ['artificial intelligence',' machine learning','llm','large language model',
        'chatbot','generative','automation','autonomous','data science','computer vision',
        'natural language',' nlp','algorithm','predictive','digital transformation',
        'govtech','robot','decision support','intelligent','ai '],
];

/**
 * Classify a tender's text into one or more vertical vectors.
 * Returns array of vector keys (pro_av / itc / hardware / si / ai).
 */
function classifyVectors($title, $desc) {
    global $KW;
    $text = ' ' . strtolower($title . ' ' . $desc) . ' ';
    $matched = [];
    foreach ($KW as $vec => $words) {
        foreach ($words as $w) {
            if (strpos($text, $w) !== false) { $matched[] = $vec; break; }
        }
    }
    return array_values(array_unique($matched));
}

function countryFlag($cc) {
    $flags = [
        'ZA' => '🇿🇦', 'KE' => '🇰🇪', 'NG' => '🇳🇬', 'ZM' => '🇿🇲',
        'GH' => '🇬🇭', 'TZ' => '🇹🇿', 'ZW' => '🇿🇼', 'MA' => '🇲🇦',
        'MU' => '🇲🇺', 'ET' => '🇪🇹', 'RW' => '🇷🇼', 'BW' => '🇧🇼',
        'SC' => '🇸🇨', 'EG' => '🇪🇬',
    ];
    return $flags[$cc] ?? '🌍';
}

/**
 * Build human-readable scope tags for a card from its vector classification
 * plus a couple of high-signal keyword extras.
 */
function scopeTags($title, $desc, $vectors) {
    $labelMap = [
        'pro_av'   => 'Pro AV & Control',
        'itc'      => 'ITC Networks',
        'hardware' => 'Hardware Supply',
        'si'       => 'Turnkey SI',
        'ai'       => 'Sovereign AI',
    ];
    $tags = [];
    foreach ($vectors as $v) { $tags[] = $labelMap[$v]; }
    $text = ' ' . strtolower($title . ' ' . $desc) . ' ';
    $extra = [
        'structured cabling' => 'Structured Cabling',
        'server'             => 'Server Infrastructure',
        'cctv'               => 'Security Hardware',
        'access control'     => 'Access Control',
        'llm'                => 'Enterprise LLM',
        'large language'     => 'Enterprise LLM',
        'fibre'              => 'Fibre Connectivity',
        'cisco'              => 'Cisco Networking',
        'q-sys'              => 'Q-SYS Audio',
        'crestron'           => 'Crestron Control',
        'ups'                => 'Power & UPS',
    ];
    foreach ($extra as $k => $lab) {
        if (strpos($text, $k) !== false && count($tags) < 4) { $tags[] = $lab; }
    }
    return array_values(array_unique($tags));
}

/**
 * Technology / skill dictionaries for the Shredder extraction engine.
 */
$SHRED = [
    'tech_stack' => [
        'Cisco' => ['cisco'],
        'Juniper' => ['juniper'],
        'Aruba / HPE' => ['aruba','hpe'],
        'Q-SYS (QSC)' => ['q-sys','qsys','qsc'],
        'Crestron' => ['crestron'],
        'Extron' => ['extron'],
        'Microsoft Azure' => ['azure'],
        'AWS' => ['aws','amazon web services'],
        'VMware' => ['vmware'],
        'Structured Cabling' => ['structured cabling','cat6','cat6a'],
        'Fibre Optic' => ['fibre','fiber','optical fibre'],
        'CCTV / Surveillance' => ['cctv','surveillance','camera'],
        'Access Control / Biometric' => ['access control','biometric'],
        'UPS / Power' => ['ups','uninterruptible'],
        'Wi-Fi / Wireless' => ['wifi','wireless','wi-fi'],
        'Firewall / Security Appliance' => ['firewall'],
        'SD-WAN' => ['sd-wan'],
        'Servers / Compute' => ['server','compute','hyperconverged'],
        'LLM / Generative AI' => ['llm','large language','generative','chatbot'],
        'Data Centre' => ['data centre','datacenter'],
        'Audio / DSP' => ['dsp','audio','mixing'],
    ],
    'compliance' => [
        'CIDB Grading' => ['cidb'],
        'SITA Accreditation' => ['sita'],
        'B-BBEE Certificate' => ['b-bbee','bbbee','bee'],
        'Tax Clearance (SARS)' => ['tax clearance','sars'],
        'CSD Registration' => ['csd','central supplier'],
        'ISO 9001' => ['iso 9001'],
        'ISO 27001' => ['iso 27001'],
        'PSIRA Registration' => ['psira'],
        'POPIA Compliance' => ['popia','protection of personal'],
        'Data Sovereignty' => ['data sovereignty','data localis','data localiz','local data'],
        'Preferential Procurement' => ['preferential procurement','80/20','90/10'],
        'Local Content' => ['local content','local production'],
        'SABS / NRCS' => ['sabs','nrcs'],
        'Valid CIPC' => ['cipc'],
    ],
    'penalties' => [
        'Compulsory Site Briefing' => ['compulsory site briefing','mandatory briefing','compulsory briefing','site briefing'],
        'Non-refundable Fee' => ['non-refundable','non refundable'],
        'Liquidated Damages' => ['liquidated damages','penalty clause','penalties for'],
        'Late Submission Rejected' => ['late submission','no late','after the closing','late tender'],
        'Performance Guarantee' => ['performance guarantee','performance bond','bid bond'],
        'Black-Listing Risk' => ['black-list','blacklist','debar'],
        'Downtime Penalty' => ['downtime','uptime','service level'],
    ],
];

/**
 * Heuristic Shredder. Returns structured analysis for a tender.
 * Confidence is derived from how much structured signal was found.
 */
function analyzeTender($t) {
    global $SHRED;
    $title = $t['title'] ?? '';
    $desc  = $t['description'] ?? '';
    $text  = ' ' . strtolower($title . ' ' . $desc) . ' ';

    $tech = [];
    foreach ($SHRED['tech_stack'] as $label => $kws) {
        foreach ($kws as $k) { if (strpos($text, $k) !== false) { $tech[] = $label; break; } }
    }
    $comp = [];
    foreach ($SHRED['compliance'] as $label => $kws) {
        foreach ($kws as $k) { if (strpos($text, $k) !== false) { $comp[] = $label; break; } }
    }
    $pen = [];
    foreach ($SHRED['penalties'] as $label => $kws) {
        foreach ($kws as $k) { if (strpos($text, $k) !== false) { $pen[] = $label; break; } }
    }

    // Pull explicit dates mentioned near penalty keywords.
    $deadlineHits = [];
    if (preg_match_all('/(compulsory|mandatory|site briefing|closing|no later than|before)\s+([0-9]{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+[0-9]{4})/i', $desc, $m)) {
        $deadlineHits = array_unique($m[0]);
    }

    $signal = count($tech) + count($comp) + count($pen) + count($deadlineHits);
    $confidence = $signal >= 6 ? 'high' : ($signal >= 3 ? 'medium' : 'low');

    return [
        'tech_stack'   => array_values(array_unique($tech)),
        'compliance'   => array_values(array_unique($comp)),
        'penalties'    => array_values(array_unique($pen)),
        'deadlines'    => array_values(array_unique($deadlineHits)),
        'confidence'   => $confidence,
        'engine'       => 'heuristic-v1',
        'note'         => 'Automated extraction from the published tender text. Verify against the official document before bidding.',
    ];
}

/**
 * Fetch the focused technology-pool tenders, applying vector + filters,
 * with pagination done in PHP (dataset is small).
 */
function getTechTenders($province, $vector, $status, $search, $page, $perPage, $country = '') {
    global $TECH_POOL;
    $where = ['sector IN (' . implode(',', array_fill(0, count($TECH_POOL), '?')) . ')'];
    $params = $TECH_POOL;

    if ($status) { $where[] = 'status = ?'; $params[] = $status; }
    if ($province) { $where[] = 'province LIKE ?'; $params[] = "%$province%"; }
    if ($country) { $where[] = 'country_code = ?'; $params[] = $country; }
    if ($search) { $where[] = '(title LIKE ? OR description LIKE ? OR issuing_dept LIKE ?)';
        $params[] = "%$search%"; $params[] = "%$search%"; $params[] = "%$search%"; }

    $sql = 'SELECT * FROM tenders WHERE ' . implode(' AND ', $where) .
           ' ORDER BY (closing_date IS NULL), closing_date ASC, created_at DESC';
    $stmt = db()->prepare($sql);
    $stmt->execute($params);
    $rows = $stmt->fetchAll();

    if ($vector && $vector !== 'all') {
        $rows = array_filter($rows, function ($r) use ($vector) {
            return in_array($vector, classifyVectors($r['title'] ?? '', $r['description'] ?? ''), true);
        });
    }
    // Soft-noise gate: exclude rows with no ICT/AV signal at all.
    if ($HIDE_NOISE) {
        $rows = array_filter($rows, function ($r) {
            return classifyVectors($r['title'] ?? '', $r['description'] ?? '') !== [];
        });
    }
    $total = count($rows);
    $rows = array_slice($rows, ($page - 1) * $perPage, $perPage);
    return ['total' => $total, 'tenders' => array_values($rows)];
}

/**
 * Live ticker stats computed strictly from the technology pool.
 */
function getHubStats() {
    global $TECH_POOL;
    $ph = implode(',', array_fill(0, count($TECH_POOL), '?'));
    $stmt = db()->prepare("SELECT * FROM tenders WHERE sector IN ($ph) AND status = 'open'");
    $stmt->execute($TECH_POOL);
    $open = $stmt->fetchAll();

    $ict = 0; $hw = 0; $ai = 0; $pa = 0;
    foreach ($open as $t) {
        $v = classifyVectors($t['title'] ?? '', $t['description'] ?? '');
        if (in_array('itc', $v, true) || in_array('si', $v, true) || in_array('hardware', $v, true)) $ict++;
        if (in_array('hardware', $v, true)) $hw++;
        if (in_array('ai', $v, true)) $ai++;
        if (in_array('pro_av', $v, true)) $pa++;
    }
    return [
        'ict_contracts' => $ict,
        'hardware_rfq'   => $hw,
        'ai_briefs'      => $ai,
        'pro_av_rfq'     => $pa,
        'open_total'     => count($open),
    ];
}

// ---------------------------------------------------------------------------
// API endpoints
// ---------------------------------------------------------------------------

$action = $_GET['action'] ?? 'dashboard';

switch ($action) {
    case 'api_tenders':
        header('Content-Type: application/json');
        $ip = $_SERVER['REMOTE_ADDR'] ?? 'anon';
        if (!rate_limit('tenders_' . $ip, 90, 60)) {
            echo json_encode(['ok' => false, 'error' => 'Rate limit exceeded. Try again shortly.']);
            exit;
        }
        $vector = $_GET['vector'] ?? '';
        if ($vector) {
            // Focused ICT/AI path.
            $page = max(1, intval($_GET['page'] ?? 1));
            $perPage = 20;
            $result = getTechTenders(
                $_GET['province'] ?? '',
                $vector,
                $_GET['status'] ?? 'open',
                $_GET['search'] ?? '',
                $page,
                $perPage,
                $_GET['country'] ?? ''
            );
            echo json_encode(['ok' => true, 'data' => $result, 'page' => $page, 'per_page' => $perPage]);
        } else {
            // Backward-compatible path (respects user sector scoping).
            $filters = [
                'province' => $_GET['province'] ?? '',
                'sector'   => $_GET['sector'] ?? '',
                'country'  => $_GET['country'] ?? '',
                'status'   => $_GET['status'] ?? 'open',
                'search'   => $_GET['search'] ?? '',
            ];
            $page = max(1, intval($_GET['page'] ?? 1));
            $perPage = 20;
            $offset = ($page - 1) * $perPage;
            $allowed = null;
            $user = getCurrentUser();
            if ($user) { $allowed = $user['allowed_sectors']; }
            $result = getTenders($filters, $perPage, $offset, $allowed);
            echo json_encode(['ok' => true, 'data' => $result, 'page' => $page, 'per_page' => $perPage]);
        }
        exit;

    case 'api_stats':
        header('Content-Type: application/json');
        echo json_encode(['ok' => true, 'stats' => getHubStats()]);
        exit;

    case 'api_shred':
        header('Content-Type: application/json');
        $id = intval($_GET['id'] ?? 0);
        $stmt = db()->prepare('SELECT * FROM tenders WHERE id = ?');
        $stmt->execute([$id]);
        $t = $stmt->fetch();
        if (!$t) { echo json_encode(['ok' => false, 'error' => 'Tender not found.']); exit; }
        // Live-LLM hook: if a client keyed engine is configured, use it here.
        // $llm = llmAnalyzeTender($t); if ($llm) { echo json_encode([...]); exit; }
        echo json_encode(['ok' => true, 'analysis' => analyzeTender($t)]);
        exit;

    case 'api_register':
        header('Content-Type: application/json');
        $input = json_decode(file_get_contents('php://input'), true) ?: $_POST;
        $name = trim($input['name'] ?? '');
        $email = trim(strtolower($input['email'] ?? ''));
        $password = $input['password'] ?? '';
        $sector = trim($input['sector'] ?? '');
        $company = trim($input['company'] ?? '');

        if (!$name || !$email || !$password) {
            echo json_encode(['ok' => false, 'error' => 'Name, email, and password are required.']);
            exit;
        }
        if (!$sector) {
            echo json_encode(['ok' => false, 'error' => 'Please choose your industry/sector. This is the field your free tenders are scoped to.']);
            exit;
        }
        if (strlen($password) < 8) {
            echo json_encode(['ok' => false, 'error' => 'Password must be at least 8 characters.']);
            exit;
        }
        $id = registerUser($name, $email, $password, $sector, $company);
        if ($id) {
            echo json_encode(['ok' => true, 'message' => 'Account created! Please log in.']);
        } else {
            echo json_encode(['ok' => false, 'error' => 'Email already registered.']);
        }
        exit;

    case 'api_login':
        header('Content-Type: application/json');
        $input = json_decode(file_get_contents('php://input'), true) ?: $_POST;
        $result = loginUser($input['email'] ?? '', $input['password'] ?? '');
        echo json_encode($result);
        exit;

    case 'api_logout':
        setcookie('tm_token', '', time() - 3600, '/');
        echo json_encode(['ok' => true]);
        exit;

    case 'api_auth':
        header('Content-Type: application/json');
        $user = getCurrentUser();
        if ($user) {
            unset($user['password_hash']);
            echo json_encode(['ok' => true, 'user' => $user]);
        } else {
            echo json_encode(['ok' => false]);
        }
        exit;
}

$user = getCurrentUser();
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Moya | ICT & AI Intelligence Command Center</title>
<link rel="icon" type="image/x-icon" href="https://www.mylo.co.za/favicon.ico">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
:root{--bg:#070b10;--bg-2:#0d141c;--panel:#121c26;--line:rgba(56,189,248,.12);--text:#e8f3fb;--muted:#7c93a6;--muted-2:#a9c4d6;--accent:#22d3ee;--accent-2:#7CFFB2;--accent-deep:#0891b2;--ok:#3ddc97;--warn:#f5b544;--danger:#ff6b6b}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',system-ui,sans-serif;background-color:var(--bg);background-image:radial-gradient(900px 520px at 50% -12%,rgba(34,211,238,.10),transparent 62%),linear-gradient(rgba(56,189,248,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(56,189,248,.045) 1px,transparent 1px);background-size:auto,42px 42px,42px 42px;background-attachment:fixed;color:var(--text);line-height:1.6}
a{color:inherit;text-decoration:none}
.wrap{max-width:1240px;margin:0 auto;padding:0 22px}
.btn{display:inline-flex;align-items:center;gap:8px;background:linear-gradient(135deg,var(--accent),var(--accent-deep));color:#04161c;font-weight:700;font-size:.9rem;padding:9px 16px;border-radius:10px;border:none;cursor:pointer;transition:transform .15s,box-shadow .2s;white-space:nowrap}
.btn:hover{transform:translateY(-1px);box-shadow:0 8px 26px rgba(34,211,238,.16)}
.btn.ghost{background:transparent;border:1px solid var(--line);color:var(--text)}
.btn.ghost:hover{box-shadow:none;border-color:var(--accent);transform:translateY(-1px)}
.btn.sm{padding:7px 13px;font-size:.82rem}
.btn.dark{background:rgba(255,255,255,.06);border:1px solid var(--line)}
.btn.ai{background:linear-gradient(135deg,#22d3ee,#14b8a6);color:#04161c}
.btn.ai:hover{box-shadow:0 8px 26px rgba(34,211,238,.34)}
.btn.ok{background:linear-gradient(135deg,#1f9d6b,#3ddc97);color:#04210f}
header{border-bottom:1px solid var(--line);padding:14px 0;background:rgba(7,11,16,.85);backdrop-filter:blur(10px);position:sticky;top:0;z-index:50;box-shadow:0 4px 24px rgba(34,211,238,.05)}
.header-inner{display:flex;align-items:center;justify-content:space-between;gap:16px}
.brand{display:flex;align-items:center;gap:11px;font-weight:800;font-size:1.3rem}
.brand .dot{width:13px;height:13px;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--accent-deep));box-shadow:0 0 12px rgba(34,211,238,.6)}
.brand .tag{font-size:9px;text-transform:uppercase;letter-spacing:.08em;padding:3px 8px;background:rgba(34,211,238,.12);border:1px solid rgba(34,211,238,.35);border-radius:6px;color:var(--accent);font-weight:700}
.nav-links{display:flex;gap:10px;align-items:center}

/* Live ticker */
.ticker{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:22px 0}
.tick{position:relative;overflow:hidden;background:linear-gradient(180deg,var(--panel),var(--bg-2));border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.tick::before{content:"";position:absolute;inset:0;background:radial-gradient(420px 160px at 100% 0%,rgba(34,211,238,.14),transparent 70%);pointer-events:none}
.tick .ico{width:38px;height:38px;border-radius:10px;display:grid;place-items:center;background:rgba(34,211,238,.14);border:1px solid rgba(34,211,238,.25);color:var(--accent);margin-bottom:12px}
.tick .num{font-size:2rem;font-weight:800;line-height:1;font-family:'JetBrains Mono',monospace}
.tick .lbl{font-size:.82rem;color:var(--muted-2);margin-top:6px}
.tick.ai .ico{background:rgba(124,255,178,.12);border-color:rgba(124,255,178,.3);color:var(--accent-2)}
.tick.hw .ico{background:rgba(245,181,68,.12);border-color:rgba(245,181,68,.3);color:var(--warn)}
.tick.proav .ico{background:rgba(167,139,250,.12);border-color:rgba(167,139,250,.3);color:#a78bfa}

/* Vertical switcher */
.switcher{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 20px}
.vbtn{display:inline-flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--line);color:var(--muted-2);font-weight:600;font-size:.86rem;padding:10px 16px;border-radius:11px;cursor:pointer;transition:all .15s}
.vbtn i{font-size:.85rem}
.vbtn:hover{border-color:var(--accent);color:var(--text)}
.vbtn.active{background:linear-gradient(135deg,rgba(34,211,238,.22),rgba(34,211,238,.1));border-color:var(--accent);color:#fff;box-shadow:0 6px 20px rgba(34,211,238,.18)}

/* Filters row */
.filters{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:18px}
.filters input,.filters select{background:var(--bg-2);border:1px solid var(--line);border-radius:10px;padding:9px 13px;color:var(--text);font-size:.9rem;outline:none;min-width:150px;font-family:inherit}
.filters input:focus,.filters select:focus{border-color:var(--accent)}

/* Tender cards */
.feed{display:flex;flex-direction:column;gap:14px;margin-bottom:30px}
.card{background:linear-gradient(180deg,var(--panel),var(--bg-2));border:1px solid var(--line);border-radius:14px;padding:20px 22px;transition:transform .15s,border-color .15s}
.card:hover{transform:translateY(-2px);border-color:var(--accent);box-shadow:0 12px 34px rgba(34,211,238,.12)}
.card-top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}
.card-title{font-size:1.08rem;font-weight:700;color:var(--text);line-height:1.3}
.card-title:hover{color:var(--accent)}
.card-dept{color:var(--muted);font-size:.85rem;margin-top:5px;display:flex;align-items:center;gap:6px}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}
.tag{display:inline-block;padding:3px 10px;border-radius:999px;font-size:.72rem;font-weight:600;background:rgba(34,211,238,.12);color:var(--accent);border:1px solid rgba(34,211,238,.22)}
.tag.warn{background:rgba(245,181,68,.12);color:var(--warn);border-color:rgba(245,181,68,.3)}
.closing{display:inline-flex;align-items:center;gap:6px;font-size:.8rem;margin-top:10px;color:var(--muted-2)}
.closing.soon{color:var(--danger);font-weight:700}
.badge-urgent{display:inline-flex;align-items:center;gap:5px;background:rgba(255,107,107,.16);color:var(--danger);border:1px solid rgba(255,107,107,.4);font-size:.7rem;font-weight:700;padding:3px 9px;border-radius:999px;margin-left:8px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px;padding-top:14px;border-top:1px solid var(--line)}
.empty{text-align:center;color:var(--muted);padding:60px 20px}
.pagination{display:flex;gap:8px;justify-content:center;margin:32px 0}
.pagination a,.pagination span{padding:8px 14px;border-radius:8px;border:1px solid var(--line);color:var(--text);text-decoration:none;font-size:.9rem;cursor:pointer}
.pagination .active{background:var(--accent);border-color:var(--accent)}

/* Modals */
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:200;align-items:center;justify-content:center;padding:22px}
.modal.active{display:flex}
.modal-box{background:var(--panel);border:1px solid var(--line);border-radius:18px;max-width:680px;width:100%;max-height:90vh;overflow-y:auto;padding:28px}
.modal-box h3{font-size:1.25rem;font-weight:800;margin-bottom:4px}
.modal-box .sub{color:var(--muted);font-size:.88rem;margin-bottom:18px}
.close-modal{position:absolute;top:16px;right:22px;background:none;border:none;color:var(--text);font-size:1.6rem;cursor:pointer}
.shred-section{margin-bottom:18px}
.shred-section h4{font-size:.78rem;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);margin-bottom:8px;display:flex;align-items:center;gap:7px}
.chip{display:inline-block;background:rgba(255,255,255,.05);border:1px solid var(--line);border-radius:8px;padding:6px 11px;font-size:.83rem;margin:0 6px 6px 0;color:var(--text)}
.chip.pen{background:rgba(255,107,107,.1);border-color:rgba(255,107,107,.3);color:#ffb3b3}
.chip.ok{background:rgba(61,220,151,.1);border-color:rgba(61,220,151,.3);color:#9af0c8}
.shred-meta{font-size:.78rem;color:var(--muted);margin-top:6px}
.shred-note{background:rgba(34,211,238,.07);border:1px solid rgba(34,211,238,.22);border-radius:10px;padding:11px 14px;font-size:.82rem;color:var(--muted-2);margin-top:10px}
.rfq-area{width:100%;min-height:260px;background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:14px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:.82rem;line-height:1.55;outline:none;resize:vertical}
.auth-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:200;align-items:center;justify-content:center;padding:22px}
.auth-modal.active{display:flex}
.auth-box{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:36px;max-width:460px;width:100%;position:relative;max-height:90vh;overflow-y:auto}
.auth-box h3{font-size:1.3rem;font-weight:800;margin-bottom:6px}
.auth-box .sub{color:var(--muted);font-size:.9rem;margin-bottom:20px}
.auth-box input,.auth-box select{width:100%;background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:11px 13px;color:var(--text);font-size:.92rem;outline:none;margin-bottom:14px;font-family:inherit}
.auth-box input:focus,.auth-box select:focus{border-color:var(--accent)}
.auth-box .btn{width:100%;justify-content:center}
.auth-box .toggle{text-align:center;margin-top:16px;color:var(--muted);font-size:.88rem}
.auth-box .toggle a{color:var(--accent);cursor:pointer}
@media(max-width:860px){.ticker{grid-template-columns:1fr}.header-inner{flex-wrap:wrap}}
</style>
</head>
<body>
<header>
  <div class="wrap header-inner">
    <div class="brand">
      <a href="/Moya/" style="color:inherit;display:flex;align-items:center;gap:11px;font-weight:800;font-size:1.3rem;text-decoration:none"><span class="dot"></span> Moya</a>
      <span class="tag">ICT &amp; AI Intelligence</span>
    </div>
    <nav class="nav-links">
      <a href="dashboard.php" class="btn ghost sm">Command Center</a>
      <a href="onboarding.php" class="btn ghost sm">Onboarding</a>
      <a href="drafting.php" class="btn ghost sm">Drafting</a>
      <a href="https://www.mylo.co.za/" class="btn ghost sm">MY-LO</a>
      <?php if ($user): ?>
        <span style="color:var(--muted-2);font-size:.88rem">Hi, <?= htmlspecialchars($user['name']) ?></span>
        <a href="account.php" class="btn ghost sm">My Sectors</a>
        <a href="compliance.php" class="btn ghost sm">My Compliance</a>
        <a href="?action=api_logout" class="btn ghost sm">Log Out</a>
      <?php else: ?>
        <button class="btn ghost sm" onclick="showAuth('login')">Log In</button>
        <a href="signup_plan.php" class="btn sm">Sign Up Free</a>
      <?php endif; ?>
    </nav>
  </div>
</header>

<div class="wrap">
<?php if ($user): ?>
<?php if (($user['payment_status'] ?? '') === 'founding_lifetime'): ?>
<div style="background:linear-gradient(135deg,rgba(245,181,68,.12),rgba(61,220,151,.1));border:1px solid rgba(245,181,68,.35);border-radius:12px;padding:12px 16px;margin:18px 0;font-size:.9rem;color:var(--text)">
  <strong style="color:var(--warn)">⚡ Founding Lifetime Member</strong> — permanent, unrestricted access to every tech vector + the AI &amp; Intelligence module.
</div>
<?php else: ?>
<div style="background:rgba(34,211,238,.08);border:1px solid rgba(34,211,238,.25);border-radius:12px;padding:12px 16px;margin:18px 0;font-size:.9rem;color:var(--muted-2)">
  <strong style="color:var(--text)">Your feed is scoped to:</strong>
  <?php
    $labels = [];
    foreach (($user['allowed_sectors'] ?? []) as $s) { $labels[] = htmlspecialchars(ucfirst(str_replace('_',' ',$s))); }
    echo implode(', ', $labels) ?: 'No sectors set';
  ?>
  &nbsp;·&nbsp; <a href="account.php">Manage / add sectors (R500 each)</a>
</div>
<?php endif; ?>
<?php endif; ?>

  <div style="text-align:center;padding:46px 0 30px">
    <h1 style="font-size:clamp(2rem,4vw,2.8rem);font-weight:800;margin-bottom:12px;text-shadow:0 0 26px rgba(34,211,238,.28)">ICT &amp; AI Intelligence Command Center</h1>
    <p style="color:var(--muted);max-width:640px;margin:0 auto">Live opportunities for high-tech infrastructure contractors, systems integrators and AI solution providers. Legacy construction &amp; plumbing noise stripped out.</p>
    <?php if (!$user): ?><a href="signup_plan.php" class="btn lg" style="margin-top:20px">Get Started Free</a><?php endif; ?>
  </div>

  <!-- Live stats ticker -->
  <div class="ticker" id="ticker">
    <div class="tick">
      <div class="ico"><i class="fa-solid fa-network-wired"></i></div>
      <div class="num" id="statIct">—</div>
      <div class="lbl">Active ICT Contracts <span style="opacity:.6">(fibre · server builds · SI)</span></div>
    </div>
    <div class="tick hw">
      <div class="ico"><i class="fa-solid fa-microchip"></i></div>
      <div class="num" id="statHw">—</div>
      <div class="lbl">Open Hardware RFQs <span style="opacity:.6">(switches · endpoints · displays)</span></div>
    </div>
    <div class="tick ai">
      <div class="ico"><i class="fa-solid fa-brain"></i></div>
      <div class="num" id="statAi">—</div>
      <div class="lbl">AI &amp; Autonomous Briefs <span style="opacity:.6">(gov LLM · workflow tenders)</span></div>
    </div>
    <div class="tick proav">
      <div class="ico"><i class="fa-solid fa-tower-broadcast"></i></div>
      <div class="num" id="statProAv">—</div>
      <div class="lbl">PRO AV RFQ's <span style="opacity:.6">(Q-SYS · Crestron · displays)</span></div>
    </div>
  </div>

  <!-- Vertical switcher -->
  <div class="switcher" id="switcher">
    <?php foreach ($VECTORS as $k => $v): ?>
      <button class="vbtn <?= $k === 'all' ? 'active' : '' ?>" data-vector="<?= $k ?>" onclick="setVector('<?= $k ?>')">
        <i class="fa-solid <?= $v['icon'] ?>"></i> <?= htmlspecialchars($v['label']) ?>
      </button>
    <?php endforeach; ?>
  </div>

  <!-- Filters -->
  <div class="filters">
    <input type="text" id="searchInput" placeholder="Search tenders, bodies, tech…">
    <select id="provinceFilter">
      <option value="">All provinces</option>
      <option value="National">National</option>
      <option value="Gauteng">Gauteng</option>
      <option value="Western Cape">Western Cape</option>
      <option value="KwaZulu-Natal">KwaZulu-Natal</option>
      <option value="Free State">Free State</option>
      <option value="Eastern Cape">Eastern Cape</option>
      <option value="Mpumalanga">Mpumalanga</option>
      <option value="Limpopo">Limpopo</option>
      <option value="North West">North West</option>
      <option value="Northern Cape">Northern Cape</option>
    </select>
    <select id="statusFilter">
      <option value="open">Open</option>
      <option value="closed">Closed</option>
      <option value="">All</option>
    </select>
    <select id="countryFilter">
      <option value="">All countries</option>
      <option value="ZA">🇿🇦 South Africa</option>
      <option value="KE">🇰🇪 Kenya</option>
      <option value="NG">🇳🇬 Nigeria</option>
      <option value="ZM">🇿🇲 Zambia</option>
      <option value="GH">🇬🇭 Ghana</option>
      <option value="TZ">🇹🇿 Tanzania</option>
      <option value="ZW">🇿🇼 Zimbabwe</option>
      <option value="MA">🇲🇦 Morocco</option>
      <option value="MU">🇲🇺 Mauritius</option>
      <option value="ET">🇪🇹 Ethiopia</option>
      <option value="RW">🇷🇼 Rwanda</option>
    </select>
    <button class="btn sm" onclick="loadTenders(1)"><i class="fa-solid fa-magnifying-glass"></i> Search</button>
  </div>

  <div class="feed" id="tenderList"><div class="empty">Loading tenders…</div></div>
  <div class="pagination" id="pagination"></div>
</div>

<!-- Shredder modal -->
<div class="modal" id="shredModal">
  <div class="modal-box" style="position:relative">
    <button class="close-modal" onclick="closeModal('shredModal')">×</button>
    <h3><i class="fa-solid fa-robot" style="color:var(--accent)"></i> Moya AI — Tender Shredder</h3>
    <div class="sub" id="shredTitle">Analyzing…</div>
    <div id="shredBody"><div class="empty">Running extraction…</div></div>
    <div class="shred-note" id="shredNote"></div>
  </div>
</div>

<!-- RFQ modal -->
<div class="modal" id="rfqModal">
  <div class="modal-box" style="position:relative">
    <button class="close-modal" onclick="closeModal('rfqModal')">×</button>
    <h3><i class="fa-solid fa-file-invoice" style="color:var(--warn)"></i> Generate Supplier RFQ</h3>
    <div class="sub">Pre-filled from the tender scope — edit and send to your suppliers.</div>
    <textarea class="rfq-area" id="rfqText"></textarea>
    <div style="display:flex;gap:10px;margin-top:14px">
      <button class="btn dark sm" onclick="copyRfq()"><i class="fa-regular fa-copy"></i> Copy</button>
      <button class="btn sm" onclick="window.print()"><i class="fa-solid fa-print"></i> Print / Save PDF</button>
    </div>
  </div>
</div>

<!-- Auth modal -->
<div class="auth-modal" id="authModal">
  <div class="auth-box">
    <button class="close-modal" onclick="closeAuth()">×</button>
    <div id="authContent"></div>
  </div>
</div>

<script>
var currentPage = 1;
var currentVector = 'all';
var TENDERS = {}; // id -> row, for RFQ generation

function setVector(v) {
  currentVector = v;
  document.querySelectorAll('.vbtn').forEach(function(b){ b.classList.toggle('active', b.dataset.vector === v); });
  loadTenders(1);
}

function showAuth(mode) {
  var html = '';
  if (mode === 'login') {
    html = `<h3>Log In</h3><p class="sub">Access your Moya dashboard</p>
      <input type="email" id="authEmail" placeholder="Email *" required>
      <input type="password" id="authPassword" placeholder="Password *" required>
      <button class="btn" onclick="submitLogin()">Log In</button>
      <p class="toggle">No account? <a onclick="showAuth('register')">Sign up free</a></p>`;
  } else {
    html = `<h3>Create Free Account</h3><p class="sub">Get access to tender alerts and saved searches</p>
      <input type="text" id="authName" placeholder="Full name *" required>
      <input type="email" id="authEmail" placeholder="Email *" required>
      <input type="password" id="authPassword" placeholder="Password (8+ chars) *" required>
      <input type="text" id="authCompany" placeholder="Company (optional)">
      <select id="authSector" required>
        <option value="" disabled selected>Select your industry / field *</option>
        <option value="ict">ICT & Technology</option>
        <option value="audio_visual">Pro Audio & Visual</option>
        <option value="construction">Construction</option>
        <option value="medical">Medical</option>
        <option value="logistics">Logistics</option>
        <option value="education">Education</option>
        <option value="energy">Energy</option>
        <option value="other">Other</option>
      </select>
      <button class="btn" onclick="submitRegister()">Create Account</button>
      <p class="toggle">Already have an account? <a onclick="showAuth('login')">Log in</a></p>`;
  }
  document.getElementById('authContent').innerHTML = html;
  document.getElementById('authModal').classList.add('active');
}
function closeAuth() { document.getElementById('authModal').classList.remove('active'); }
function closeModal(id) { document.getElementById(id).classList.remove('active'); }

async function submitLogin() {
  const btn = document.querySelector('#authContent .btn');
  btn.textContent = 'Logging in…'; btn.disabled = true;
  try {
    const r = await fetch('?action=api_login', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('authEmail').value,password:document.getElementById('authPassword').value})});
    const d = await r.json();
    if (d.ok) { closeAuth(); location.reload(); } else { alert(d.error || 'Login failed'); }
  } catch(e) { alert('Network error'); }
  btn.textContent = 'Log In'; btn.disabled = false;
}
async function submitRegister() {
  const btn = document.querySelector('#authContent .btn');
  btn.textContent = 'Creating…'; btn.disabled = true;
  try {
    const r = await fetch('?action=api_register', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:document.getElementById('authName').value,email:document.getElementById('authEmail').value,password:document.getElementById('authPassword').value,company:document.getElementById('authCompany').value,sector:document.getElementById('authSector').value})});
    const d = await r.json();
    if (d.ok) { alert('Account created! Please log in.'); showAuth('login'); } else { alert(d.error || 'Registration failed'); }
  } catch(e) { alert('Network error'); }
  btn.textContent = 'Create Account'; btn.disabled = false;
}

async function loadStats() {
  try {
    const r = await fetch('?action=api_stats');
    const d = await r.json();
    if (d.ok) {
      document.getElementById('statIct').textContent = d.stats.ict_contracts;
      document.getElementById('statHw').textContent = d.stats.hardware_rfq;
      document.getElementById('statAi').textContent = d.stats.ai_briefs;
      document.getElementById('statProAv').textContent = d.stats.pro_av_rfq;
    }
  } catch(e) {}
}

async function loadTenders(page) {
  page = page || 1;
  currentPage = page;
  const params = new URLSearchParams({
    action: 'api_tenders',
    vector: currentVector,
    province: document.getElementById('provinceFilter').value,
    status: document.getElementById('statusFilter').value,
    country: document.getElementById('countryFilter').value,
    search: document.getElementById('searchInput').value,
    page: page
  });
  try {
    const r = await fetch('?' + params.toString());
    const d = await r.json();
    if (d.ok) {
      renderTenders(d.data.tenders);
      renderPagination(d.data.total, d.per_page, page);
    }
  } catch(e) {
    document.getElementById('tenderList').innerHTML = '<div class="empty">Error loading tenders.</div>';
  }
}

function esc(s){ return (s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function renderTenders(tenders) {
  if (!tenders.length) {
    const countryFilter = document.getElementById('countryFilter').value;
    const isComingSoon = countryFilter && !['ZA','KE'].includes(countryFilter);
    if (isComingSoon) {
      document.getElementById('tenderList').innerHTML =
        '<div class="empty"><div style="font-size:3rem;margin-bottom:12px">🚧</div>' +
        '<strong style="color:var(--muted-2);font-size:1.1rem">Market launching soon</strong><br>' +
        '<span style="color:var(--muted)">We\'re building the tender feed for this country.</span><br>' +
        '<span style="color:var(--muted);font-size:.85rem">South Africa and Kenya are live now.</span></div>';
      return;
    }
    document.getElementById('tenderList').innerHTML = '<div class="empty">No tech tenders match this view. Try another vector or clear filters.</div>';
    return;
  }
  let html = '';
  tenders.forEach(function(t) {
    TENDERS[t.id] = t;
    const daysLeft = t.closing_date ? Math.ceil((new Date(t.closing_date) - new Date()) / 86400000) : null;
    const overdue = daysLeft !== null && daysLeft < 0;
    const urgent = daysLeft !== null && daysLeft >= 0 && daysLeft < 2;
    let closingHtml;
    if (t.closing_date) {
      const d = new Date(t.closing_date);
      const ds = d.toLocaleDateString('en-ZA', {day:'numeric',month:'short',year:'numeric'});
      closingHtml = `<span class="closing ${urgent?'soon':''}"><i class="fa-regular fa-clock"></i> Closes ${ds}${overdue?' (OVERDUE)':(daysLeft<2?'':'' )}</span>` + (urgent ? `<span class="badge-urgent"><i class="fa-solid fa-triangle-exclamation"></i> CLOSES &lt;48H</span>` : '');
    } else {
      closingHtml = `<span class="closing"><i class="fa-regular fa-clock"></i> Closing date TBC</span>`;
    }
    const isPdf = (t.source_url||'').toLowerCase().includes('.pdf');
    const scope = (t._tags||[]);
    const tagHtml = scope.map(function(s){ return `<span class="tag">${esc(s)}</span>`; }).join('');
    html += `<div class="card">
      <div class="card-top">
        <div style="min-width:0">
          <a href="${t.source_url||'#'}" target="_blank" class="card-title">${esc(t.title)}</a>
          <div class="card-dept"><i class="fa-regular fa-building"></i> ${esc(t.issuing_dept||'Issuing body not specified')} ${t.province?('· '+esc(t.province)):''} ${t.country_code?`<span class="tag" style="background:rgba(113,112,255,.15);color:#9b9aff">${countryFlag(t.country_code)} ${esc(t.country||t.country_code)}</span>`:''}</div>
        </div>
      </div>
      ${tagHtml?`<div class="tags">${tagHtml}</div>`:''}
      ${closingHtml}
      <div class="actions">
        <a class="btn dark sm" href="${t.source_url||'#'}" target="_blank"><i class="fa-solid fa-file-pdf"></i> ${isPdf?'View Source PDF':'View Source'}</a>
        <button class="btn ai sm" onclick="openShred(${t.id})"><i class="fa-solid fa-robot"></i> Analyze with Moya AI</button>
        <button class="btn ok sm" onclick="openRfq(${t.id})"><i class="fa-solid fa-file-invoice"></i> Generate Supplier RFQ</button>
      </div>
    </div>`;
  });
  document.getElementById('tenderList').innerHTML = html;
}

function renderPagination(total, perPage, currentPage) {
  const totalPages = Math.ceil(total / perPage);
  if (totalPages <= 1) { document.getElementById('pagination').innerHTML = ''; return; }
  let html = '';
  for (let i = 1; i <= totalPages; i++) {
    html += `<a class="${i === currentPage ? 'active' : ''}" onclick="loadTenders(${i});return false;">${i}</a>`;
  }
  document.getElementById('pagination').innerHTML = html;
}

// --- Shredder ---
async function openShred(id) {
  const t = TENDERS[id];
  document.getElementById('shredTitle').textContent = t ? t.title : 'Analyzing…';
  document.getElementById('shredBody').innerHTML = '<div class="empty">Running extraction…</div>';
  document.getElementById('shredNote').textContent = '';
  document.getElementById('shredModal').classList.add('active');
  try {
    const r = await fetch('?action=api_shred&id=' + id);
    const d = await r.json();
    if (!d.ok) { document.getElementById('shredBody').innerHTML = '<div class="empty">'+esc(d.error||'Analysis failed')+'</div>'; return; }
    const a = d.analysis;
    const chip = (arr, cls) => (arr||[]).map(function(x){ return `<span class="chip ${cls||''}">${esc(x)}</span>`; }).join('') || '<span class="chip">None detected</span>';
    const confColor = a.confidence==='high'?'var(--ok)':(a.confidence==='medium'?'var(--warn)':'var(--muted)');
    let html = '';
    html += `<div class="shred-section"><h4><i class="fa-solid fa-microchip"></i> Core Technical Stack Required</h4>${chip(a.tech_stack)}</div>`;
    html += `<div class="shred-section"><h4><i class="fa-solid fa-certificate"></i> Mandatory Compliance & Certifications</h4>${chip(a.compliance,'ok')}</div>`;
    html += `<div class="shred-section"><h4><i class="fa-solid fa-triangle-exclamation"></i> Hidden Penalties & Deadlines</h4>${chip(a.penalties,'pen')}`;
    if (a.deadlines && a.deadlines.length) { html += `<div class="shred-meta" style="margin-top:8px"><i class="fa-regular fa-calendar"></i> Dates mentioned: ${esc(a.deadlines.join(' · '))}</div>`; }
    html += `</div>`;
    html += `<div class="shred-meta" style="margin-top:10px">Extraction confidence: <b style="color:${confColor}">${a.confidence.toUpperCase()}</b> · Engine: ${esc(a.engine)}</div>`;
    document.getElementById('shredBody').innerHTML = html;
    document.getElementById('shredNote').textContent = a.note;
  } catch(e) {
    document.getElementById('shredBody').innerHTML = '<div class="empty">Network error during analysis.</div>';
  }
}

// --- RFQ generator ---
function openRfq(id) {
  const t = TENDERS[id];
  if (!t) return;
  const tags = (t._tags||[]).join(', ');
  const today = new Date().toLocaleDateString('en-ZA',{day:'numeric',month:'long',year:'numeric'});
  const txt =
`SUPPLIER REQUEST FOR QUOTATION (RFQ)
Generated ${today} via Moya

TENDER REFERENCE
Title: ${t.title}
Issuing Body: ${t.issuing_dept||'Not specified'}
Province: ${t.province||'Not specified'}
Closing Date: ${t.closing_date||'TBC'}
Source: ${t.source_url||'N/A'}

SCOPE / VECTORS
${tags||'General ICT'}

REQUEST
Please provide a formal quotation for supply / delivery / implementation of the above, including:
  - Unit pricing and volume breaks
  - Lead times and availability
  - Warranty & after-sales support
  - Compliance evidence (B-BBEE, tax clearance, CSD)
  - Validity period of quotation

Reply to: [YOUR EMAIL] by [YOUR DEADLINE].

— Generated by Moya (ICT & AI Intelligence Hub)`;
  document.getElementById('rfqText').value = txt;
  document.getElementById('rfqModal').classList.add('active');
}
function copyRfq() {
  const ta = document.getElementById('rfqText');
  ta.select(); document.execCommand('copy');
  alert('RFQ copied to clipboard.');
}

// Attach vector-derived scope tags to each row before render.
// We compute on the client from cached row text (server already filtered).
function decorate() {
  Object.keys(TENDERS).forEach(function(id){
    var t = TENDERS[id];
    if (!t._tags) t._tags = deriveTags(t.title, t.description);
  });
}
// Lightweight client mirror of the PHP scopeTags for instant card labels.
function deriveTags(title, desc) {
  var text = (' '+(title||'')+' '+(desc||'')+' ').toLowerCase();
  var m = [];
  if (/audio|av |q-sys|crestron|extron|projector|video wall|led wall|pa system|conferenc|dsp|speaker|microphone|broadcast|signage/.test(text)) m.push('Pro AV & Control');
  if (/network|fibre|fiber|cabling|cisco|switch|router|wifi|wireless|firewall|vpn|vsat|sd-wan|wan|lan|data centre|connectivity/.test(text)) m.push('ITC Networks');
  if (/hardware|server|endpoint|laptop|desktop|monitor|printer|ups|rfq|supply|cctv|camera|access control|biometric|compute|workstation/.test(text)) m.push('Hardware Supply');
  if (/turnkey|implement|install|rollout|roll out|migration|managed service|maintenance|supply and install|design and build|professional services|upgrade/.test(text)) m.push('Turnkey SI');
  if (/artificial intelligence| machine learning|llm|large language|chatbot|generative|automation|autonomous|data science|computer vision|digital transformation|govtech|robot/.test(text)) m.push('Sovereign AI');
  if (/structured cabling/.test(text)) m.push('Structured Cabling');
  if (/server/.test(text)) m.push('Server Infrastructure');
  return m.slice(0,4);
}
// Wrap renderTenders to decorate tags first.
const _renderTenders = renderTenders;
renderTenders = function(tenders){
  tenders.forEach(function(t){ if(!t._tags) t._tags = deriveTags(t.title, t.description); });
  _renderTenders(tenders);
};

// Init
loadStats();
loadTenders(1);

// Shared referral banner (uniform across site)
(function(){
  try{ if(localStorage.getItem('mylo_banner_ack')==='closed') return; }catch(e){}
  var m=document.createElement('div'); m.id='bannerMount'; document.body.appendChild(m);
  fetch('/banner.html').then(function(r){return r.ok?r.text():Promise.reject();}).then(function(h){
    m.innerHTML=h;
    var s=m.querySelectorAll('script');
    for(var i=0;i<s.length;i++){
      var n=document.createElement('script');
      if(s[i].src){ n.src=s[i].src; } else { n.textContent=s[i].textContent; }
      document.body.appendChild(n);
    }
  }).catch(function(){});
})();
</script>
</body>
</html>
