# PVAT/PRAT metabolic–RAAS discovery workflow

This workflow is intended for sparse public-omics questions where strict same-sample tissue + phenotype matching can hide useful studies.

## Scientific question

Discover transcriptomic and proteomic evidence from perivascular adipose tissue (PVAT) and perirenal adipose tissue (PRAT) across control and metabolic disease states, then annotate and interrogate local renin–angiotensin–aldosterone system (RAAS) biology.

RAAS is deliberately an annotation/mechanism layer, not an inclusion requirement. A dataset can therefore be retained even when its repository metadata does not mention RAAS, because RAAS genes/proteins may still be measurable in the matrix.

## Evidence hierarchy

- **Tier A:** human PVAT/PRAT omics with prediabetes or metabolic syndrome.
- **Tier B:** human PVAT/PRAT omics with insulin resistance, obesity, type 2 diabetes, or hypertension.
- **Tier C:** mouse/rat PVAT/PRAT omics and mechanistic/RAAS perturbation studies.
- **Context candidates:** target PVAT/PRAT studies lacking an explicit target phenotype in repository metadata. These are retained for manual review rather than rejected during discovery.

## RAAS interrogation panel

Core classical/counter-regulatory components include `AGT`, `REN`, `ACE`, `ACE2`, `AGTR1`, `AGTR2`, `MAS1`, `NR3C2`, `CYP11B2`, and `ATP6AP2`. Additional peptidases and alternative angiotensin-processing components in the discovery vocabulary include `LNPEP`, `ANPEP`, `ENPEP`, `MME`, and `CTSG`/chymase terminology.

The panel is a hypothesis-focused annotation set. Downstream analysis should also use unbiased differential expression/protein abundance and pathway enrichment rather than limiting inference to these genes.

## Usage

```powershell
omnibioseek search --profile profiles\pvat_prat_raas_metabolic.yaml
omnibioseek curate --profile profiles\pvat_prat_raas_metabolic.yaml
```

Review all `needs_review` records before download/analysis. In a sparse field, `needs_review` is an intentional discovery state, not a failed match.

After curation:

```powershell
omnibioseek download --profile profiles\pvat_prat_raas_metabolic.yaml --approved-only
omnibioseek prepare --profile profiles\pvat_prat_raas_metabolic.yaml
omnibioseek integrate --profile profiles\pvat_prat_raas_metabolic.yaml
```

## Important limitations

The current adapters search OmicsDI, NCBI GEO/SRA, and Arc scBaseCount. This change improves recall and biological framing but does not yet implement literature-to-accession mining or a separate direct BioStudies adapter. PRIDE records reachable through OmicsDI remain the current proteomics route. Those capabilities should be added as subsequent milestones rather than implied by this profile.
