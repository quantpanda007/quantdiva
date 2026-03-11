/**
 * Cap — instrument module (placeholder)
 *
 * TODO: Add fieldGroups for grouped 3-column layout when needed.
 * Currently uses flat FIELDS from schema_master.js.
 */

const cap_floor = {

  fieldGroups: null,  // null = use flat FIELDS fallback

  flatFields: null,   // null = use FIELDS['cap_floor'] from schema_master

  apiType: 'cap_floor',

  mapPayload: null,   // null = use default collectPayload logic

  bulkUpload: false,

  onFieldChange: null,
};

INSTRUMENT_REGISTRY['cap_floor'] = cap_floor;
