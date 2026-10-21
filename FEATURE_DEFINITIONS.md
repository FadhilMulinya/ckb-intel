# CKB Wallet Behaviour Intelligence - Feature Definitions

## Overview

The CKB Wallet Behaviour Intelligence project analyzes observable on-chain wallet activity on Nervos CKB using features extracted from transactions and Cells.

These features measure capacity usage, Cell relationships, and type-script characteristics to help identify structural patterns across wallet addresses.

Below are the definitions of six feature fields used in the project, including how each is calculated and what it represents.

## Feature Definitions

### 1. `target_consumed_capacity`

**Meaning:** The total capacity of Cells consumed as transaction inputs by the address being analyzed.

**Calculation:** Sum the capacities of all resolved input Cells associated with the target address.

`target_consumed_capacity = sum(target input Cell capacities)`

**Unit:** Shannon.

**What it represents:** The amount of Cell capacity observed being consumed by the address during the study period.

### 2. `capacity_repeat_ratio`

**Meaning:** How frequently identical Cell capacity values appear across the address’s observed transaction inputs and outputs.

**Calculation:** Count the observations belonging to capacity values that occur more than once, divided by the total number of observed capacity values.

`capacity_repeat_ratio = repeated capacity observations / total capacity observations`

**Example:** If the observed capacities are `100, 100, 200`, two out of three observations have a repeated value.

The ratio is `2 / 3 = 0.667`.

**Unit:** Ratio between 0 and 1.

**What it represents:** How common repeated Cell capacity amounts are in the observed transactions.

### 3. `target_net_capacity_delta`

**Meaning:** The difference between the capacity created and consumed by the target address.

**Calculation:**

`target_net_capacity_delta = total target output capacity - total target input capacity`

**Unit:** Signed shannon.

**What it represents:**

- Positive value: More capacity was created than consumed.
- Negative value: More capacity was consumed than created.
- Zero: The observed input and output capacity totals are equal.

### 4. `lineage_depth`

**Meaning:** The depth of connected Cell and transaction relationships observed for an address.

**Calculation:** Trace connections between previously created Cells, the transactions consuming them, and the resulting output Cells. Record the maximum observable transaction-hop depth.

**Unit:** Number of transaction hops.

**What it represents:** How many connected transaction steps can be traced through the observed Cell history.

### 5. `type_family_count`

**Meaning:** The number of distinct recognized type-script families appearing in the address’s observed Cells.

**Calculation:** Match observed type scripts against the project’s configured script-family registry and count the distinct recognized families.

**Unit:** Number of recognized script families.

**What it represents:** How many different recognized type-script families, such as Nervos DAO, Type ID, or xUDT, appear in the observed Cells.

### 6. `unique_type_script_count`

**Meaning:** The number of distinct type-script hashes appearing in the address’s observed Cells.

**Calculation:** Collect the type-script hashes from observed input and output Cells and count the unique values.

`unique_type_script_count = count(distinct type-script hashes)`

**Unit:** Number of unique type-script hashes.

**What it represents:** The number of distinct type scripts observed, regardless of whether they belong to a recognized script family.

---

These six features are used to describe the characteristics that distinguish the observed PCA4 groups.

The implementation is available in the [Feature V2 source code](https://github.com/FadhilMulinya/ckb-intel/tree/3ffa0873a230edae6a181e1c5144ffb635dd7af6/classifier-service/wallet_intelligence/features_v2).