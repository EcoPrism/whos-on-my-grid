"""SHA-256 digests of the US cases in tests/test_us_golden.py, recorded from a git
worktree at b02e7d1 (step 5, before Ireland) on 2026-10-29, re-recorded on
2026-10-29 for the plain-words round (glance block, folded strip lines, the noise
sentence only within half a mile, card caption). Constants only: a change here is
a deliberate change to what a US brief says, and the build log must say why."""

GOLDEN: dict[str, str] = {
    "system_prompts": "370b60886458ead985dbd7f6208e9f44b606fcc6dcc35046923b139f4f80ec00",
    "section_prompts": "cc6a4d8483a87439d837e8c737b87d509b0787480ac0a8f2bafe802b0ce9ca56",
    "house_prompts": "6a88be53f9bf14a1ed41517d3791542007049418d6af06515551dee838dde665",
    "draft_schemas": "6c6c52111e7287847406034ad07745354101a24459dfa045b6820c035c13cc25",
    "brief_agent": "dbbc0309b9679701d13da92d9b2e681699c5f2af808b732d7bc5fbc4b5813e88",
    "brief_full": "a1970506c96416c58a09c45c7f7c5aa81a3e0bbb43d8ef40fd20ed5c2a3f0673",
    "brief_full_variants": "02e6d53fd04673cf695221d415bafe95bf09397ca0ac7c53db241ab33f3281c8",
    "brief_tariff": "e2445c076be00e437093951489f7a0c990530c6cf6fc725a6a2faee890b1f1d3",
    "utility_and_protection_claims": "4964e765c5839b73eaa99157421afaa346720b338952f3295e1ff5b2cf67c453",
    "brief_step4": "2d7316715d556649c06710d404b8e3b52f086a296d24fb2f15a32f16ebcb7584",
    "ground_notes": "3cffbb745f407df1104ec79c02409f8383c714a5a3a6f189275554ac8fb0365f",
    "pulse": "378e7f4f122393af9dfba5161e78736e0acb838ad65266328a569addf519b31b",
    "health": "ab2ff0c55c8005cec2a90a5ea4683c0038cee5fa9e69b6ca421a8b55b01da9aa",
    "cards": "9a7ea4975ea5d5f9c0cdc1fe810f9803193bc74fad1be7a1f744f1918d5f23d7",
    "assembled_cards": "af58743b126314f21615519cfa44ab75f936ce9cf3d9b1539fd55b1c33fce80e",
    "static_meta": "370cf0b3ee03fbcff2a94a95d99421cbc7edb442cd988ce9cfd00eb1eb1f96a7",
}
