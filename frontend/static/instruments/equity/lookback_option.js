/**
 * Lookback Option — instrument module (placeholder)
 *
 * TODO: Add fieldGroups for grouped 3-column layout when needed.
 * Currently uses flat FIELDS from schema_master.js.
 */

const lookback_option = {

  fieldGroups: null,  // null = use flat FIELDS fallback

  flatFields: null,   // null = use FIELDS['lookback_option'] from schema_master

  apiType: 'lookback_option',

  mapPayload: null,   // null = use default collectPayload logic

  bulkUpload: false,

  onFieldChange: null,
};

INSTRUMENT_REGISTRY['lookback_option'] = lookback_option;
