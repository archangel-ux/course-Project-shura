"""Printable PDF documents: invoices for receipts, issues, transfers and stocktakes."""

from flask import Blueprint, Response, abort

from app.i18n import t
from app.services import pdf
from app.store import parallel
from app.web.session import current_org, get_store, login_required

bp = Blueprint("documents", __name__, url_prefix="/documents")


def pdf_response(content, filename, download=False):
    disposition = "attachment" if download else "inline"
    return Response(content, mimetype="application/pdf",
                    headers={"Content-Disposition": f'{disposition}; filename="{filename}"'})


def requisites_loader():
    """A callable for parallel(): session values are read here, in the request thread."""
    org = current_org() or {}
    store = get_store()
    fallback = {"name": org.get("name", "")}
    return lambda: (store.get_organization(org["id"]) if org.get("id") else None) or fallback


@bp.route("/<int:document_id>.pdf")
@login_required
def invoice(document_id):
    store = get_store()
    document, lines, org = parallel(
        lambda: store.get_document(document_id),
        lambda: store.list_movements(document_id=document_id),
        requisites_loader(),
    )
    if document is None:
        abort(404)
    content = pdf.invoice(document, lines, org, t)
    return pdf_response(content, f"qoima_{document['doc_type'].lower()}_{document['number']}.pdf")
