"""The export's columns per PROJECT_BRIEF.md §4. Schema names only - these are
published in the brief and carry no corpus content, so they are safe to commit."""

EXPECTED_COLUMNS = [
    "id",
    "userCreatedId",
    "userAssignedId",
    "statusId",
    "priorityId",
    "personId",
    "title",
    "description",
    "vehicleYear",
    "customData",
    "merchantName",
    "endCustomerName",
    "timestampCreated",
    "categoryId",
    "deadline",
    "merchantId",
    "endCustomerId",
    "vehicleHours",
    "vehicleSerialNo",
    "vehicleId",
    "vehicleModelId",
    "solutions",
    "vehicleStatus",
    "contactEmail",
    "contactPhone",
    "ticketNumber",
    "vehicleSerialIndex",
    "merchantNumber",
    "merchantPhoneNumber",
    "endCustomerNumber",
    "endCustomerPhoneNumber",
    "contactPhoneTrimmed",
    "showInProteam",
    "contractTransaction",
    "contractItems",
    "lastModifiedUser",
    "subStatusString",
    "subStatusChanged",
]

TEXT_COLUMNS = ["title", "description", "solutions", "customData"]
DIMENSION_COLUMNS = [
    "statusId",
    "categoryId",
    "priorityId",
    "vehicleModelId",
    "subStatusString",
    "vehicleStatus",
    "showInProteam",
]
MAX_DIMENSION_CARDINALITY = 200

# Columns whose per-value vocabulary is worth reporting, so a category or a model can be
# characterised without the client's lookup tables. vehicleModelId is here because the
# prefix-based family proxy failed on real data - the values are opaque numeric FKs.
DIMENSION_HINT_COLUMNS = ["categoryId", "statusId", "priorityId", "vehicleModelId"]
