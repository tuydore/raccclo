"""Reddit ACCount CLOner. A simple script to copy subreddits and
multireddits from one account to another."""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "Tudor Tomescu"
__license__ = "MIT"
__email__ = "tuydore+raccclo@protonmail.com"
__description__ = ("Simple way to transfer subreddits and "
                   "multireddits from one Reddit account to another.")

import argparse
import json
from dataclasses import dataclass
from enum import Enum, auto
from getpass import getpass
from pathlib import Path
from typing import Any, Generator
from warnings import warn

from requests import Response, get, post
from requests.auth import HTTPBasicAuth

USER_AGENT: str = f"raccclo/{__version__}"
ACCESS_TOKEN_URL: str = "https://www.reddit.com/api/v1/access_token"
OAUTH_URL: str = "https://oauth.reddit.com"


def password_request_data(username: str, password: str) -> dict[str, str]:
    """HTTP password request data."""
    return {
        "grant_type": "password",
        "username": username,
        "password": password
    }


def get_token(data: dict[str, str], auth: HTTPBasicAuth) -> str:
    """Gets an authentication token."""

    return post(
        ACCESS_TOKEN_URL,
        auth=auth,
        data=data,
        headers={
            "User-Agent": USER_AGENT
        },
    ).json()["access_token"]


def chunks(list_: list[Any],
           chunk_size: int) -> Generator[list[Any], None, None]:
    """Equally-sized list chunks."""
    for i in range(0, len(list_), chunk_size):
        yield list_[i:i + chunk_size]


def print_status_code(response: Response) -> None:
    """Prints response status to the terminal."""

    if response.status_code == 200:
        print("OK")
    else:
        print(f"ERROR {response.status_code}")
        print(response.content)


class Target(Enum):
    """Users targeted by app. Subreddits get copied from SOURCE to DESTINATION."""

    SOURCE = auto()
    DESTINATION = auto()

    def get_data_from_cli(self) -> dict[str, str]:
        """Reads HTTP password request data from the CLI."""
        return password_request_data(
            getpass(f"{self.name.capitalize()} Username: "),
            getpass(f"{self.name.capitalize()} Password: "))

    def get_token_from_cli(self, auth: HTTPBasicAuth) -> str:
        """Gets an authentication token from the CLI."""
        return get_token(self.get_data_from_cli(), auth)


@dataclass
class Subreddit:
    """Basic subreddit information."""

    id: str
    name: str


@dataclass
class Multireddit:
    """Basic multireddit information."""

    name: str
    path: str
    subreddits: list[str]


@dataclass
class SubredditCloner:
    """Copies subreddits from one account to another."""

    auth: HTTPBasicAuth
    src_access_token: str
    dst_access_token: str

    @staticmethod
    def from_cli() -> SubredditCloner:
        """Prompt for client ID and secret token from CLI (via hidden password input)
        and create a new cloner."""

        auth = HTTPBasicAuth(getpass("Client ID: "), getpass("Secret Token: "))
        src_token = Target.SOURCE.get_token_from_cli(auth)
        dst_token = Target.DESTINATION.get_token_from_cli(auth)
        return SubredditCloner(auth, src_token, dst_token)

    @staticmethod
    def from_json(filepath: str | Path) -> SubredditCloner:
        """Load a cloner from a JSON file."""

        warn((
            "Please DO NOT forget configuration files containing credentials lying around. "
            "Delete this file when you're done."))

        info = json.load(open(filepath, "r", encoding="utf-8"))
        auth = HTTPBasicAuth(info.get("client_id"), info.get("secret_token"))

        src_token = get_token(
            password_request_data(
                info.get("src_username"),
                info.get("src_password"),
            ), auth)

        dst_token = get_token(
            password_request_data(
                info.get("dst_username"),
                info.get("dst_password"),
            ), auth)

        return SubredditCloner(auth, src_token, dst_token)

    def headers(self, which: Target) -> dict[str, str]:
        """Returns headers dictionary, with a specific access token."""

        token = self.src_access_token if which == Target.SOURCE else self.dst_access_token
        return {"User-Agent": USER_AGENT, "Authorization": f"bearer {token}"}

    def src_subscriptions(self) -> list[Subreddit]:
        """Returns the subreddits the source account is subscribed to."""

        params = {"limit": "100"}
        after = None
        subreddits = []

        while True:
            # return next batch
            if after is not None:
                params["after"] = after

            subs = get(f"{OAUTH_URL}/subreddits/mine/subscriber",
                       headers=self.headers(Target.SOURCE),
                       params=params).json()["data"]["children"]

            if not subs:
                break

            # update subreddit list
            for sub in subs:
                subreddits.append(
                    Subreddit(sub["data"]["display_name"], sub["data"]["id"]))

            # set after to the last subreddit listed
            after = subs[-1]["kind"] + "_" + subs[-1]["data"]["id"]

        return subreddits

    def dst_subscribe(self, subreddits: list[Subreddit]) -> None:
        """Subscribe the destination user to a number of subreddits."""

        params = {"action": "sub"}

        for chunk in chunks(subreddits, 100):
            names = ",".join((c.name for c in chunk))
            params["sr_name"] = names
            response = post(f"{OAUTH_URL}/api/subscribe",
                            headers=self.headers(Target.DESTINATION),
                            params=params)

            print_status_code(response)

    def src_multireddits(self) -> list[Multireddit]:
        """Return a list of multireddits."""
        multis = get(f"{OAUTH_URL}/api/multi/mine",
                     headers=self.headers(Target.SOURCE)).json()
        return [
            Multireddit(
                name=m["data"]["name"],
                subreddits=[s["name"] for s in m["data"]["subreddits"]],
                path=m["data"]["path"]) for m in multis
        ]

    def username(self, target: Target) -> str:
        """Return Reddit username."""
        return get(f"{OAUTH_URL}/api/v1/me",
                   headers=self.headers(target)).json()["name"]

    def dst_subscribe_multis(self, multireddits: list[Multireddit]) -> None:
        """Add multis to current user."""

        for multireddit in multireddits:
            model = {
                "display_name": multireddit.name,
                "subreddits": [{
                    "name": s
                } for s in multireddit.subreddits],
                "visibility": "private",
            }

            path = multireddit.path.replace(self.username(Target.SOURCE),
                                            self.username(Target.DESTINATION))

            response = post(
                f"{OAUTH_URL}/api/multi{path}",
                headers=self.headers(Target.DESTINATION),
                params={"model": json.dumps(model)},
            )
            print_status_code(response)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        prog="RACCCLO",
        description=
        "Copy subreddits and multireddits from one account to another.")
    parser.add_argument("--config",
                        type=str,
                        help="Path to JSON configuration file.")
    parser.add_argument("--terminal",
                        action="store_true",
                        help="Input credentials from the terminal.")
    args = parser.parse_args()

    if not args.terminal and args.config is None:
        print(("At least one of --terminal and --config must be given. "
               "Please run --help for more information."))
        exit(1)

    elif args.terminal:
        cloner = SubredditCloner.from_cli()

    else:
        cloner = SubredditCloner.from_json(args.config)

    print("Loading subreddits from source...")
    subreddits = cloner.src_subscriptions()

    print("Subscribing destination...")
    cloner.dst_subscribe(subreddits)

    print("Loading multireddits from source...")
    multireddits = cloner.src_multireddits()

    print("Multi(?)scribing destination...")
    cloner.dst_subscribe_multis(multireddits)
