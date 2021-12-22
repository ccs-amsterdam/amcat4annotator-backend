import logging

from flask import Blueprint, request, abort, make_response, jsonify, g
from werkzeug.exceptions import HTTPException

from amcat4annotator import auth, rules
from amcat4annotator.db import create_codingjob, Unit, CodingJob, Annotation
from amcat4annotator.auth import multi_auth, check_admin

app_annotator = Blueprint('app_annotator', __name__)


@app_annotator.errorhandler(HTTPException)
def bad_request(e):
    logging.error(str(e))
    status = e.get_response(request.environ).status_code
    return jsonify(error=str(e)), status


def _job(job_id: int):
    job = CodingJob.get_or_none(CodingJob.id == job_id)
    if not job:
        abort(404)
    return job


@app_annotator.route("/codingjob", methods=['POST'])
@multi_auth.login_required
def create_job():
    """
    Create a new codingjob. Body should be json structured as follows:

     {
      "title": <string>,
      "codebook": {.. blob ..},
      "rules": {
        "ruleset": <string>, .. additional options ..
      },
      "units": [
        {"unit": {.. blob ..},
         "gold": {.. blob ..},  # optional, include correct answer here for gold questions
        }
        ..
      ],
      "provenance": {.. blob ..},  # optional
     }

    Where ..blob.. indicates that this is not processed by the backend, so can be annotator specific.
    See the annotator documentation for additional informations.

    The rules distribute how units should be distributed, how to deal with quality control, etc.
    The ruleset name specifies the class of rules to be used (currently "crowd" or "expert").
    Depending on the ruleset, additional options can be given.
    See the rules documentation for additional information
    """
    check_admin()
    job = request.get_json(force=True)
    if {"title", "codebook", "units", "rules"} - set(job.keys()):
        return make_response({"error": "Codinjob is missing keys"}, 400)
    job = create_codingjob(title = job['title'], codebook=job['codebook'], provenance=job.get('provenance'),
                           rules=job['rules'], units=job['units'])
    return make_response(dict(id=job.id), 201)


@app_annotator.route("/codingjob/<job_id>", methods=['GET'])
@multi_auth.login_required
def get_job(job_id):
    """
    Return a single coding job definition
    """
    check_admin()
    job = _job(job_id)
    units = list(Unit.select(Unit.id, Unit.gold, Unit.status, Unit.unit, Unit.status)
                 .where(Unit.codingjob==job).tuples().dicts().execute())
    return jsonify({
        "title": job.title,
        "codebook": job.codebook,
        "provenance": job.provenance,
        "rules": job.rules,
        "units": units
    })


@app_annotator.route("/codingjob/<job_id>/codebook", methods=['GET'])
@multi_auth.login_required
def get_codebook(job_id):
    job = _job(job_id)
    return jsonify(job.codebook)


@app_annotator.route("/codingjob/<job_id>/progress", methods=['GET'])
@multi_auth.login_required
def progress(job_id):
    job = _job(job_id)
    return jsonify(rules.get_progress_report(job, g.current_user))


@app_annotator.route("/codingjob/<job_id>/unit", methods=['GET'])
@multi_auth.login_required
def get_unit(job_id):
    """
    Retrieve a single unit to be coded.
    If ?index=i is specified, seek a specific unit. Otherwise, return the next unit to code
    """
    job = _job(job_id)
    index = request.args.get("index")
    if index:
        u = rules.seek_unit(job, g.current_user, index=int(index))
    else:
        u = rules.get_next_unit(job, g.current_user)
    if not u:
        abort(404)
    result = {'id': u.id, 'unit': u.unit}
    a = list(Annotation.select().where(Annotation.unit == u.id, Annotation.coder == g.current_user.id))
    if a:
        result['annotation'] = a[0].annotation
    return jsonify(result)


@app_annotator.route("/codingjob/<job_id>/unit/<unit_id>/annotation", methods=['POST'])
@multi_auth.login_required
def set_annotation(job_id, unit_id):
    """Set the annotations for a specific unit"""
    job = _job(job_id)
    annotation = request.get_json(force=True)
    if not annotation:
        abort(400)
    unit = Unit.get_or_none(Unit.id == unit_id)
    if not unit:
        abort(404)
    Annotation.create(unit=unit.id, coder=g.current_user.id, annotation=annotation)
    return make_response('', 204)


@app_annotator.route("/token", methods=['GET'])
@multi_auth.login_required
def get_token():
    return jsonify({"token": auth.get_token(g.current_user)})
