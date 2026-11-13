import hashlib

from agent.prompts import PROMPT_REGISTRY

# A released prompt version is never edited: a change gets a new version, so every trace and
# eval result labelled with a version name means one exact text. Add a line here when you add
# a version; never change an existing line.
RELEASED = {
    "v1": "4efaa9d0049ab7c885913fedcdbcc06e21af89d98024c5197a2502ca61e68404",
    "v2": "f25557bdcec0f0a2a0938e80017dcdc9437107d6bff6d09033dcb976eee2d553",
    "v3": "35db40c6a5a7679bac461a6b53f8100763c9613183a57aa624e5a556a524a1d2",
    "v4": "7c733da02201ee7353472616fbb8cdc2da1c3e2e48252920054c9b9d03e15efd",
    "v5": "02dee1d9ff67a21cd3456569d007dc2b3d17bebb7c64b45026ed5a5d97a6d3d9",
    "v6": "0d1c669a1c4839d08800ded83f293b699938d5e2061e60d4909068b8f8a5b54f",
}


def test_released_prompt_versions_never_change():
    for version, digest in RELEASED.items():
        assert hashlib.sha256(PROMPT_REGISTRY[version].encode()).hexdigest() == digest, (
            f"prompt {version} was edited; add a new version instead")
