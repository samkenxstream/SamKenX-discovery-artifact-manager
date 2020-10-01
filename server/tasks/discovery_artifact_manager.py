# Copyright 2017, Google Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Contains update/query functions for discovery-artifact-manager."""

import datetime
import glob
import json
import os
from os.path import join
from tempfile import TemporaryDirectory

from github import Github

from tasks import _git, accounts
from tasks._check_output import check_output

# "admin:directory_v1" and "admin:datatransfer_v1" are incorrectly marked in
# the Discovery index as not preferred.
_ACTUALLY_PREFERRED = ['admin:directory_v1', 'admin:datatransfer_v1']
# Override with enviroment variable DISCOVERY_ARTIFACT_MANAGER_REPO_NAME.
_REPO_NAME = 'discovery-artifact-manager'
# Override with enviroment variable DISCOVERY_ARTIFACT_MANAGER_REPO_PATH.
_REPO_PATH = 'googleapis/discovery-artifact-manager'


def _repo_name() -> str:
    return os.environ.get("DISCOVERY_ARTIFACT_MANAGER_REPO_NAME") or _REPO_NAME


def _repo_path() -> str:
    return os.environ.get("DISCOVERY_ARTIFACT_MANAGER_REPO_PATH") or _REPO_PATH


def discovery_documents(filepath, preferred=False, skip=None):
    """Returns a map of API IDs to Discovery document filenames.

    Args:
        filepath (str): the directory to work in. Discovery documents are
            downloaded to this directory.
        preferred (bool, optional): if true, only APIs marked as preferred are
            returned.
        skip (list, optional): a list of API IDs to skip.

    Returns:
        dict(string, string): a map of API IDs to Discovery document
            filenames.
    """
    repo = _git.clone_from_github(_repo_path(), join(filepath, _repo_name()))
    filenames = glob.glob(join(repo.filepath, 'discoveries/*.json'))
    # Skip index.json.
    filenames = [x for x in filenames if os.path.basename(x) != 'index.json']
    ddocs = {}
    for filename in filenames:
        id_ = None
        with open(filename) as file_:
            id_ = json.load(file_)['id']
        # If an ID has already been visited, skip it.
        if id_ in ddocs:
            continue
        ddocs[id_] = filename
    if skip:
        _ = [ddocs.pop(id_, None) for id_ in skip]
    if not preferred:
        return ddocs
    index = {}
    with open(join(repo.filepath, 'discoveries/index.json')) as file_:
        index = json.load(file_)
    for api in index['items']:
        id_ = api['id']
        if id_ in _ACTUALLY_PREFERRED:
            continue
        if api['preferred']:
            continue
        ddocs.pop(id_, None)
    return ddocs


def update(filepath, github_account):
    """Updates the discovery-artifact-manager repository.

    Args:
        filepath (str): the directory to work in.
        github_account (GitHubAccount): the GitHub account to commit and push
            with.
    """
    repo = _git.clone_from_github(
        _repo_path(), join(filepath, _repo_name()), github_account=github_account)
    if _update_disco(repo, github_account) > 0:
        repo.push()

def _update_disco(repo: _git.Repository, github_account: accounts.GitHubAccount) -> int:
    """Invokes updatedisco on the repo.  Returns the number of commits."""
    with TemporaryDirectory() as gopath:
        os.makedirs(join(gopath, 'src'))
        check_output(['ln', '-s',
                      join(repo.filepath, 'src'),
                      join(gopath, 'src/discovery-artifact-manager')])
        env = os.environ.copy()
        env['GOPATH'] = gopath
        check_output(['go', 'run', 'src/main/updatedisco/main.go'],
                     cwd=repo.filepath,
                     env=env)
    repo.add(['discoveries'])
    if not repo.diff_name_status():
        return 0
    repo.commit('Autogenerated Discovery document update',
                github_account.name,
                github_account.email)
    return 1


def create_pull_request(filepath, github_account):
    """Creates a pull request on the discovery-artifact-manager repository.

    Args:
        filepath (str): the directory to work in.
        github_account (GitHubAccount): the GitHub account to commit with.
    """
    repo = _git.clone_from_github(
        _repo_path(), join(filepath, _repo_name()), github_account=github_account)
    branch = ('update-discovery-artifacts-' +
        datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    repo.checkout_new(branch)
    if _update_disco(repo, github_account) > 0:
        repo.push(branch=branch)
        gh = Github(github_account.personal_access_token)
        gh_repo = gh.get_repo(_repo_path())
        pr = gh_repo.create_pull(
            title='chore: autogenerated discovery document update',
            body='',
            base='master',
            head=branch)


