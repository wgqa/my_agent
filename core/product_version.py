"""Current product identity; transport schemas and historical freezes are separate."""

PRODUCT_NAME = "Evidence-Grounded AI Engineering Agent"
PRODUCT_VERSION = "2.0.0-dev"
PRODUCT_STAGE = "development"


def product_identity() -> dict:
    return {
        "schema_version": "product_version_v1",
        "product_name": PRODUCT_NAME,
        "version": PRODUCT_VERSION,
        "stage": PRODUCT_STAGE,
    }
