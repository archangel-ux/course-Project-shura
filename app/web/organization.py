"""Organization requisites, team members with roles, invitations and switching organizations."""

import logging

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for

from app.i18n import error_text, t
from app.services import inventory, notify
from app.services.validators import ValidationError, parse_email
from app.store import StoreError, parallel
from app.web.session import current_auth, current_org, get_store, load_organization, login_required, permission_required

logger = logging.getLogger(__name__)
bp = Blueprint("organization", __name__)


def invite_url(token):
    return current_app.config["SITE_URL"] + url_for("organization.invite", token=token)


def _render(errors=None, form=None, status=200):
    store = get_store()
    org = current_org()
    is_owner = org["role"] == "owner"
    details, team, invites, organizations = parallel(
        lambda: store.get_organization(org["id"]),
        store.team,
        (lambda: store.list_invites(org["id"])) if is_owner else (lambda: []),
        store.my_organizations,
    )
    return render_template(
        "organization.html", details=details or {}, team=team, invites=invites, organizations=organizations,
        roles=inventory.ROLES, errors=errors or {}, form=form, me=current_auth()["user_id"],
        new_invite=session.pop("new_invite", None), invite_url=invite_url,
    ), status


@bp.route("/organization")
@login_required
def index():
    if current_org() is None:
        abort(403)
    return _render()


@bp.route("/organization/requisites", methods=["POST"])
@permission_required("manage")
def requisites():
    try:
        data = inventory.clean_organization_form(request.form)
        get_store().update_organization(current_org()["id"], data)
    except (ValidationError, StoreError) as error:
        return _render({"requisites": error_text(error)}, request.form, 400)
    load_organization()
    flash(t("msg.requisites_saved"), "success")
    return redirect(url_for("organization.index"))


@bp.route("/organization/invites", methods=["POST"])
@permission_required("manage")
def create_invite():
    role = request.form.get("role")
    try:
        email = parse_email(request.form.get("email"))
        if role not in inventory.ROLES:
            raise ValidationError("err.invalid_choice")
        token = get_store().create_invite(email, role)
    except (ValidationError, StoreError) as error:
        return _render({"invite": error_text(error)}, None, 400)

    link = invite_url(token)
    session["new_invite"] = {"email": email, "url": link}
    config = current_app.config
    if notify.email_enabled(config):
        try:
            notify.send_email(config, email, t("invite.mail_subject", org=current_org()["name"]),
                              t("invite.mail_text", org=current_org()["name"], role=t(f"role.{role}"), url=link))
            flash(t("msg.invite_sent", email=email), "success")
        except notify.NotifyError as error:
            logger.warning("Invite email failed: %s", error)
            flash(t("msg.invite_created"), "success")
    else:
        flash(t("msg.invite_created"), "success")
    return redirect(url_for("organization.index") + "#team")


@bp.route("/organization/invites/<int:invite_id>/cancel", methods=["POST"])
@permission_required("manage")
def cancel_invite(invite_id):
    get_store().cancel_invite(invite_id)
    flash(t("msg.invite_cancelled"), "success")
    return redirect(url_for("organization.index") + "#team")


@bp.route("/organization/members/<user_id>/role", methods=["POST"])
@permission_required("manage")
def member_role(user_id):
    role = request.form.get("role")
    if role not in inventory.ROLES:
        abort(400)
    try:
        get_store().set_member_role(user_id, role)
    except StoreError as error:
        flash(error_text(error), "error")
        return redirect(url_for("organization.index") + "#team")
    if user_id == current_auth()["user_id"]:
        load_organization()
    flash(t("msg.role_saved"), "success")
    return redirect(url_for("organization.index") + "#team")


@bp.route("/organization/members/<user_id>/remove", methods=["POST"])
@login_required
def remove_member(user_id):
    leaving = user_id == current_auth()["user_id"]
    try:
        get_store().remove_member(user_id)
    except StoreError as error:
        flash(error_text(error), "error")
        return redirect(url_for("organization.index") + "#team")
    if leaving:
        load_organization()
        flash(t("msg.left_organization"), "success")
        return redirect(url_for("main.dashboard"))
    flash(t("msg.member_removed"), "success")
    return redirect(url_for("organization.index") + "#team")


@bp.route("/organization/switch", methods=["POST"])
@login_required
def switch():
    try:
        get_store().switch_organization(int(request.form.get("organization_id") or 0))
    except (StoreError, ValueError):
        flash(t("err.forbidden"), "error")
        return redirect(url_for("main.dashboard"))
    org = load_organization()
    flash(t("msg.switched", name=(org or {}).get("name", "")), "success")
    return redirect(url_for("main.dashboard"))


@bp.route("/invite/<token>", methods=["GET", "POST"])
@login_required
def invite(token):
    store = get_store()
    info = store.invite_info(token)
    if request.method == "POST" and info and info.get("matches"):
        try:
            store.accept_invite(token)
        except StoreError as error:
            flash(error_text(error), "error")
            return redirect(url_for("organization.invite", token=token))
        org = load_organization()
        flash(t("msg.invite_accepted", name=(org or {}).get("name", "")), "success")
        return redirect(url_for("main.dashboard"))
    return render_template("invite.html", info=info, token=token, email=current_auth()["email"])
