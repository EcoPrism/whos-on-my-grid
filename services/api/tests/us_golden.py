"""SHA-256 digests of the US cases in tests/test_us_golden.py, recorded from a git
worktree at b02e7d1 (step 5, before Ireland) on 2026-10-29. Constants only: a
change here is a deliberate change to what a US brief says, and the build log
must say why."""

GOLDEN: dict[str, str] = {
    "system_prompts": "dd20fa5afe4a1ccce942c5b0877b13c7644cea7bd9619b4104d0411f8da0d5bb",
    "section_prompts": "cc6a4d8483a87439d837e8c737b87d509b0787480ac0a8f2bafe802b0ce9ca56",
    "house_prompts": "6a88be53f9bf14a1ed41517d3791542007049418d6af06515551dee838dde665",
    "draft_schemas": "6c6c52111e7287847406034ad07745354101a24459dfa045b6820c035c13cc25",
    "brief_agent": "599439796dc85c5093a8338231a052f317bd824076472f5c5615da55d08abf05",
    "brief_full": "fbb4eef224c94f65cd478001b6c0daf021674a841fd03492a5594c99167ad722",
    "brief_full_variants": "8f3ffa24a11d03cf4f63a1681956f8ca982322d225334c3fb98a2935150ef125",
    "brief_tariff": "cd68f42913ef7c30cfcfcff68341f7d9cb3515f2ad44bb496ae8dd4fcf7912b1",
    "utility_and_protection_claims": "4964e765c5839b73eaa99157421afaa346720b338952f3295e1ff5b2cf67c453",
    "brief_step4": "c130dfd94d297704adc9826da5c3cfb6cabf1219635060b1a61e8fb2c7544220",
    "ground_notes": "3cffbb745f407df1104ec79c02409f8383c714a5a3a6f189275554ac8fb0365f",
    "pulse": "378e7f4f122393af9dfba5161e78736e0acb838ad65266328a569addf519b31b",
    "health": "ab2ff0c55c8005cec2a90a5ea4683c0038cee5fa9e69b6ca421a8b55b01da9aa",
    "cards": "5df56214c66df859f759414982dd6f5eba8f470adb7b50a2ba8975cfee35c8fd",
    "assembled_cards": "0e0a3793831487e540f6375c1f71cc105ef6463f67520916042529870e771451",
    "static_meta": "370cf0b3ee03fbcff2a94a95d99421cbc7edb442cd988ce9cfd00eb1eb1f96a7",
}
