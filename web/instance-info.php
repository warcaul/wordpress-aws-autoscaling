<?php
// Shows which instance served this request, read from the instance
// metadata service (IMDSv2) every time the page is loaded. Used to show
// how the load balancer spreads requests across instances.

const METADATA_URL = 'http://169.254.169.254/latest';

// IMDSv2: first get a short-lived session token with a PUT request
function metadata_token() {
    $context = stream_context_create(['http' => [
        'method'  => 'PUT',
        'header'  => "X-aws-ec2-metadata-token-ttl-seconds: 60\r\n",
        'timeout' => 2,
    ]]);
    return @file_get_contents(METADATA_URL . '/api/token', false, $context);
}

// Then read one metadata item using that token
function metadata($path, $token) {
    $context = stream_context_create(['http' => [
        'header'  => "X-aws-ec2-metadata-token: $token\r\n",
        'timeout' => 2,
    ]]);
    $value = @file_get_contents(METADATA_URL . "/meta-data/$path", false, $context);
    return $value === false ? 'unavailable' : htmlspecialchars($value);
}

$token = metadata_token();
$items = [
    'Instance ID'       => 'instance-id',
    'Private IP'        => 'local-ipv4',
    'Public IP'         => 'public-ipv4',
    'Availability zone' => 'placement/availability-zone',
    'AMI ID'            => 'ami-id',
    'Instance type'     => 'instance-type',
];
?>
<!DOCTYPE html>
<html>
<head>
  <title>Instance info</title>
  <style>
    body { font-family: sans-serif; margin: 2em; }
    td   { padding: 0.3em 1em 0.3em 0; }
  </style>
</head>
<body>
  <h1>Served by this instance</h1>
  <table>
    <?php foreach ($items as $label => $path): ?>
      <tr><td><b><?= $label ?></b></td><td><?= metadata($path, $token) ?></td></tr>
    <?php endforeach; ?>
  </table>
  <p>Time: <?= date('Y-m-d H:i:s T') ?></p>
</body>
</html>