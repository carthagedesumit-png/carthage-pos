"""Product identification and label platform endpoints."""

from fastapi import APIRouter, Depends, Query

from auth import UserSession
from app.api.dependencies import get_current_session
from app.api.pagination import data_response
from app.api.schemas import BarcodeAssignRequest, BarcodeGenerateRequest, LabelPreviewRequest, LabelPrintRequest
from app.barcodes.barcode_service import assign_identifier, generate_identifier, get_product_identifiers, lookup_product
from app.barcodes.label_service import preview_label, print_labels, reprint_label_job, supported_templates
from app.barcodes.reporting import barcode_audit, duplicate_identifiers, labels_printed, last_print_dates, products_without_barcode
from app.core.exceptions import BarcodeError


router = APIRouter(prefix="/barcodes", tags=["barcodes and labels"])


@router.get("/templates")
def templates(_session: UserSession = Depends(get_current_session)):
    return data_response(supported_templates())


@router.get("/lookup")
def lookup(value: str = Query(min_length=1, max_length=2048), store_id: int | None = None,
           session: UserSession = Depends(get_current_session)):
    product = lookup_product(value, store_id=store_id, session=session)
    if not product:
        raise BarcodeError("Product not found for identifier.")
    return data_response(product)


@router.get("/products/{product_id}/identifiers")
def identifiers(product_id: int, _session: UserSession = Depends(get_current_session)):
    return data_response(get_product_identifiers(product_id))


@router.post("/products/{product_id}/generate", status_code=201)
def generate(product_id: int, payload: BarcodeGenerateRequest,
             session: UserSession = Depends(get_current_session)):
    return data_response(generate_identifier(session, product_id, payload.format,
                                              payload.identifier_type, payload.regenerate))


@router.post("/products/{product_id}/generate-qr", status_code=201)
def generate_qr(product_id: int, session: UserSession = Depends(get_current_session)):
    return data_response(generate_identifier(session, product_id, "QR", "QR"))


@router.post("/products/{product_id}/assign", status_code=201)
def assign(product_id: int, payload: BarcodeAssignRequest,
           session: UserSession = Depends(get_current_session)):
    return data_response(assign_identifier(session, product_id, payload.value, payload.format,
                                            payload.identifier_type, payload.primary))


@router.post("/labels/preview")
def preview(payload: LabelPreviewRequest, session: UserSession = Depends(get_current_session)):
    return data_response(preview_label(session, payload.product_id, payload.template_code,
                                       payload.store_id, payload.width_mm, payload.height_mm,
                                       payload.include_cost))


@router.post("/labels/print")
def print_batch(payload: LabelPrintRequest, session: UserSession = Depends(get_current_session)):
    return data_response(print_labels(session, [item.model_dump() for item in payload.items],
                                      payload.template_code, payload.store_id,
                                      payload.printer_profile))


@router.post("/labels/jobs/{job_id}/reprint")
def reprint(job_id: int, printer_profile: str | None = None,
            session: UserSession = Depends(get_current_session)):
    return data_response(reprint_label_job(session, job_id, printer_profile))


@router.get("/reports/products-without-barcode")
def without_barcode(store_id: int | None = None,
                    session: UserSession = Depends(get_current_session)):
    return data_response(products_without_barcode(session, store_id))


@router.get("/reports/duplicates")
def duplicates(session: UserSession = Depends(get_current_session)):
    return data_response(duplicate_identifiers(session))


@router.get("/reports/labels-printed")
def printed(store_id: int | None = None, session: UserSession = Depends(get_current_session)):
    return data_response(labels_printed(session, store_id))


@router.get("/reports/last-print-dates")
def print_dates(store_id: int | None = None,
                session: UserSession = Depends(get_current_session)):
    return data_response(last_print_dates(session, store_id))


@router.get("/reports/audit")
def audit(product_id: int | None = None, session: UserSession = Depends(get_current_session)):
    return data_response(barcode_audit(session, product_id))
