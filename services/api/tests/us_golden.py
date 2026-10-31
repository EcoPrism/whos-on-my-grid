"""SHA-256 digests of the US cases in tests/test_us_golden.py, recorded from a git
worktree at b02e7d1 (step 5, before Ireland) on 2026-10-29, re-recorded on
2026-10-29 for the plain-words round (glance block, folded strip lines, the noise
sentence only within half a mile, card caption), and on 2026-10-30 for engine-written
bill and tariff gaps. Constants only: a change here is
a deliberate change to what a US brief says, and the build log must say why."""

GOLDEN: dict[str, str] = {
    "system_prompts": "1720d36fac0901c82adbb8fcc3e44e8b8a6f8ef6fb619f8d1419ddc5c12eca82",
    "section_prompts": "cc6a4d8483a87439d837e8c737b87d509b0787480ac0a8f2bafe802b0ce9ca56",
    "house_prompts": "6a88be53f9bf14a1ed41517d3791542007049418d6af06515551dee838dde665",
    "draft_schemas": "6c6c52111e7287847406034ad07745354101a24459dfa045b6820c035c13cc25",
    "brief_agent": "02d1f421feec50114d85e74e28f0655127ef03a785274a385bfd990cf94a94a6",
    "brief_full": "e40dce5d91ee6f273006b4a5a35982a25e28a9685edaf18c0ac9ed9ca6828445",
    "brief_full_variants": "cdfd83f0ed3c2bfe53db636c1305530744f42e2f062f997f1af911ccb028a49b",
    "brief_tariff": "100ddf6f899171a99092e10ca1eb6e5fb092ab0853753a6ed0f302c68fe10ab2",
    "utility_and_protection_claims": "4964e765c5839b73eaa99157421afaa346720b338952f3295e1ff5b2cf67c453",
    "brief_step4": "f595bfd976048d987be88d6ee2828b05b3bccd591bd00db811992580b7304526",
    "ground_notes": "3cffbb745f407df1104ec79c02409f8383c714a5a3a6f189275554ac8fb0365f",
    "pulse": "378e7f4f122393af9dfba5161e78736e0acb838ad65266328a569addf519b31b",
    "health": "ab2ff0c55c8005cec2a90a5ea4683c0038cee5fa9e69b6ca421a8b55b01da9aa",
    "cards": "9a7ea4975ea5d5f9c0cdc1fe810f9803193bc74fad1be7a1f744f1918d5f23d7",
    "assembled_cards": "af58743b126314f21615519cfa44ab75f936ce9cf3d9b1539fd55b1c33fce80e",
    "static_meta": "370cf0b3ee03fbcff2a94a95d99421cbc7edb442cd988ce9cfd00eb1eb1f96a7",
}
