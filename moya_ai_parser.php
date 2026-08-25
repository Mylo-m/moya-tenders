<?php
/**
 * Moya — Standalone AI Shredder / Requirement Parser endpoint.
 *
 * Self-contained so it can be called directly without booting the full
 * dashboard. Mirrors analyzeTender() in dashboard.php (same dictionaries,
 * same output shape) so behaviour is identical. Heuristic v1 — zero LLM cost.
 *
 * Input (JSON POST):
 *   { "tender_text": "..." }                  -> shred raw/pasted text
 *   { "id": 123 }                            -> shred a stored tender by id
 *   { "title": "...", "description": "..." } -> shred title+desc
 *
 * Output (JSON):
 *   { "status":"success", "analysis": { tech_stack, compliance, penalties,
 *     deadlines, confidence, engine, note } }
 */
header('Content-Type: application/json');
require_once __DIR__ . '/moya.php';

// ---- Shredder dictionaries (kept in sync with dashboard.php) ----
$SHRED = [
    'tech_stack' => [
        'Cisco' => ['cisco'], 'Juniper' => ['juniper'], 'Aruba / HPE' => ['aruba','hpe'],
        'Q-SYS (QSC)' => ['q-sys','qsys','qsc'], 'Crestron' => ['crestron'], 'Extron' => ['extron'],
        'Microsoft Azure' => ['azure'], 'AWS' => ['aws','amazon web services'], 'VMware' => ['vmware'],
        'Structured Cabling' => ['structured cabling','cat6','cat6a'], 'Fibre Optic' => ['fibre','fiber','optical fibre'],
        'CCTV / Surveillance' => ['cctv','surveillance','camera'], 'Access Control / Biometric' => ['access control','biometric'],
        'UPS / Power' => ['ups','uninterruptible'], 'Wi-Fi / Wireless' => ['wifi','wireless','wi-fi'],
        'Firewall / Security Appliance' => ['firewall'], 'SD-WAN' => ['sd-wan'], 'Servers / Compute' => ['server','compute','hyperconverged'],
        'LLM / Generative AI' => ['llm','large language','generative','chatbot'], 'Data Centre' => ['data centre','datacenter'],
        'Audio / DSP' => ['dsp','audio','mixing'],
    ],
    'compliance' => [
        'CIDB Grading' => ['cidb'], 'SITA Accreditation' => ['sita'], 'B-BBEE Certificate' => ['b-bbee','bbbee','bee'],
        'Tax Clearance (SARS)' => ['tax clearance','sars'], 'CSD Registration' => ['csd','central supplier'],
        'ISO 9001' => ['iso 9001'], 'ISO 27001' => ['iso 27001'], 'PSIRA Registration' => ['psira'],
        'POPIA Compliance' => ['popia','protection of personal'], 'Data Sovereignty' => ['data sovereignty','data localis','data localiz','local data'],
        'Preferential Procurement' => ['preferential procurement','80/20','90/10'], 'Local Content' => ['local content','local production'],
        'SABS / NRCS' => ['sabs','nrcs'], 'Valid CIPC' => ['cipc'],
    ],
    'penalties' => [
        'Compulsory Site Briefing' => ['compulsory site briefing','mandatory briefing','compulsory briefing','site briefing'],
        'Non-refundable Fee' => ['non-refundable','non refundable'], 'Liquidated Damages' => ['liquidated damages','penalty clause','penalties for'],
        'Late Submission Rejected' => ['late submission','no late','after the closing','late tender'],
        'Performance Guarantee' => ['performance guarantee','performance bond','bid bond'], 'Black-Listing Risk' => ['black-list','blacklist','debar'],
        'Downtime Penalty' => ['downtime','uptime','service level'],
    ],
];

function analyzeTenderLocal($t) {
    global $SHRED;
    $title = $t['title'] ?? '';
    $desc  = $t['description'] ?? '';
    $text  = ' ' . strtolower($title . ' ' . $desc) . ' ';
    $tech = [];
    foreach ($SHRED['tech_stack'] as $label => $kws) { foreach ($kws as $k) { if (strpos($text, $k) !== false) { $tech[] = $label; break; } } }
    $comp = [];
    foreach ($SHRED['compliance'] as $label => $kws) { foreach ($kws as $k) { if (strpos($text, $k) !== false) { $comp[] = $label; break; } } }
    $pen = [];
    foreach ($SHRED['penalties'] as $label => $kws) { foreach ($kws as $k) { if (strpos($text, $k) !== false) { $pen[] = $label; break; } } }
    $deadlineHits = [];
    if (preg_match_all('/(compulsory|mandatory|site briefing|closing|no later than|before)\s+([0-9]{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+[0-9]{4})/i', $desc, $m)) {
        $deadlineHits = array_unique($m[0]);
    }
    $signal = count($tech) + count($comp) + count($pen) + count($deadlineHits);
    $confidence = $signal >= 6 ? 'high' : ($signal >= 3 ? 'medium' : 'low');
    return [
        'tech_stack' => array_values(array_unique($tech)),
        'compliance' => array_values(array_unique($comp)),
        'penalties'  => array_values(array_unique($pen)),
        'deadlines'  => array_values(array_unique($deadlineHits)),
        'confidence' => $confidence,
        'engine'     => 'heuristic-v1',
        'note'       => 'Automated extraction from the published tender text. Verify against the official document before bidding.',
    ];
}

$in = json_decode(file_get_contents('php://input'), true) ?: [];
if (!empty($in['id'])) {
    $stmt = db()->prepare('SELECT * FROM tenders WHERE id = ?');
    $stmt->execute([intval($in['id'])]);
    $t = $stmt->fetch();
    if (!$t) { echo json_encode(['status'=>'error','message'=>'Tender not found.']); exit; }
    $title = $t['title'] ?? ''; $desc = $t['description'] ?? '';
} elseif (!empty($in['tender_text'])) {
    $title = ''; $desc = (string)$in['tender_text'];
} elseif (!empty($in['title']) || !empty($in['description'])) {
    $title = (string)($in['title'] ?? ''); $desc = (string)($in['description'] ?? '');
} else {
    echo json_encode(['status'=>'error','message'=>'No tender text, id, or title/description provided for analysis.']); exit;
}

echo json_encode(['status'=>'success','analysis'=>analyzeTenderLocal(['title'=>$title,'description'=>$desc])]);
exit;
?>
