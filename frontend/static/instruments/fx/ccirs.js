/**
 * Cross Currency IRS — instrument module (placeholder)
 *
 * TODO: Add fieldGroups for grouped 3-column layout when needed.
 * Currently uses flat FIELDS from schema_master.js.
 */

const ccirs = {

  fieldGroups: null,  // null = use flat FIELDS fallback

  flatFields: null,   // null = use FIELDS['ccirs'] from schema_master

  apiType: 'ccirs',

  mapPayload: null,   // null = use default collectPayload logic

  bulkUpload: false,

  onFieldChange: null,
};

INSTRUMENT_REGISTRY['ccirs'] = ccirs;
