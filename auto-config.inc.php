<?php

// Environment-driven config for BMLT in containers.
defined('BMLT_EXEC') or define('BMLT_EXEC', 1);

$dbName = getenv('BMLT_DB_NAME') ?: 'rootserver';
$dbUser = getenv('BMLT_DB_USER') ?: 'rootserver';
$dbPassword = getenv('BMLT_DB_PASSWORD') ?: '';
$dbServer = getenv('BMLT_DB_HOST') ?: 'db';
$dbPrefix = getenv('BMLT_DB_PREFIX') ?: 'na';
$dbType = 'mysql';

// Optional extras
$gkey = getenv('BMLT_GOOGLE_MAPS_KEY') ?: null;

$region_bias = getenv('BMLT_REGION_BIAS') ?: 'us';
$comdef_distance_units = getenv('BMLT_DISTANCE_UNITS') ?: 'mi';
$comdef_global_language = getenv('BMLT_DEFAULT_LANGUAGE') ?: 'en';

$mapLongitude = getenv('BMLT_MAP_LONGITUDE');
$mapLatitude = getenv('BMLT_MAP_LATITUDE');
$mapZoom = getenv('BMLT_MAP_ZOOM');
$search_spec_map_center = [
    'longitude' => $mapLongitude !== false ? (float) $mapLongitude : -118.563659,
    'latitude' => $mapLatitude !== false ? (float) $mapLatitude : 34.235918,
    'zoom' => $mapZoom !== false ? (int) $mapZoom : 6,
];

$default_duration_time = getenv('BMLT_DEFAULT_DURATION') ?: '01:30';
$g_defaultClosedStatus = getenv('BMLT_DEFAULT_CLOSED_STATUS') !== false
    ? filter_var(getenv('BMLT_DEFAULT_CLOSED_STATUS'), FILTER_VALIDATE_BOOL)
    : true;
$g_enable_language_selector = getenv('BMLT_ENABLE_LANGUAGE_SELECTOR') !== false
    ? filter_var(getenv('BMLT_ENABLE_LANGUAGE_SELECTOR'), FILTER_VALIDATE_BOOL)
    : false;

