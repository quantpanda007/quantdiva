/**
 * Collar — instrument module (placeholder)
 *
 * TODO: Add fieldGroups for grouped 3-column layout when needed.
 * Currently uses flat FIELDS from schema_master.js.
 */

const ir_collar = {

  fieldGroups: null,  // null = use flat FIELDS fallback

  flatFields: null,   // null = use FIELDS['ir_collar'] from schema_master

  apiType: 'ir_collar',

  mapPayload: null,   // null = use default collectPayload logic

  bulkUpload: false,

  onFieldChange: null,
};

INSTRUMENT_REGISTRY['ir_collar'] = ir_collar;
