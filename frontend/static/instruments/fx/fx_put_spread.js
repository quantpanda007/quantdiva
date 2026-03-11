/**
 * FX Put Spread — instrument module (placeholder)
 *
 * TODO: Add fieldGroups for grouped 3-column layout when needed.
 * Currently uses flat FIELDS from schema_master.js.
 */

const fx_put_spread = {

  fieldGroups: null,  // null = use flat FIELDS fallback

  flatFields: null,   // null = use FIELDS['fx_put_spread'] from schema_master

  apiType: 'fx_put_spread',

  mapPayload: null,   // null = use default collectPayload logic

  bulkUpload: false,

  onFieldChange: null,
};

INSTRUMENT_REGISTRY['fx_put_spread'] = fx_put_spread;
