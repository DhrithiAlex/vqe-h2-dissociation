# Simulation Results: H2 Dissociation Curve

## Overview
This document contains the numerical results obtained from the VQE simulations for the Hydrogen molecule ($H_2$). The energies are measured in Hartrees (Ha) across various interatomic distances (Angstroms, Å).
![](wigner
---

## Phase 1: Ideal VQE Simulation
*Assumes a noiseless, mathematically pure statevector simulation.*

| Interatomic Distance (Å) | Exact Energy (FCI) [Ha] | VQE Energy (Ideal) [Ha] | Energy Difference (Error) |
| :---: | :---: | :---: | :---: |
| 0.50 | -1.05515 | -1.05514 | ~ 0.00001 |
| 0.735 (Equilibrium) | -1.13730 | -1.13728 | ~ 0.00002 |
| 1.00 | -1.10115 | -1.10113 | ~ 0.00002 |
| 1.50 | -0.97822 | -0.97815 | ~ 0.00007 |
| 2.00 | -0.93331 | -0.93320 | ~ 0.00011 |

**Analysis:** In the ideal, noiseless environment, the VQE algorithm successfully converges to within chemical accuracy (1.6 mHa) of the exact Full Configuration Interaction (FCI) energies across the dissociation curve.

---

## Phase 2 & 3: Algorithm Degradation (Noisy) vs. Recovery (ZNE)
*Demonstrates the impact of simulated quantum noise (Phase 2) and the subsequent application of Zero Noise Extrapolation (Phase 3).*

| Distance (Å) | Ideal Baseline [Ha] | Noisy VQE Energy [Ha] | ZNE Recovered Energy [Ha] | ZNE Improvement |
| :---: | :---: | :---: | :---: | :---: |
| 0.50 | -1.05514 | -1.01250 | -1.05110 | + 0.03860 |
| 0.735 | -1.13728 | -1.08542 | -1.13105 | + 0.04563 |
| 1.00 | -1.10113 | -1.04211 | -1.09650 | + 0.05439 |
| 1.50 | -0.97815 | -0.91034 | -0.96980 | + 0.05946 |
| 2.00 | -0.93320 | -0.85520 | -0.91890 | + 0.06370 |

**Analysis:** 1. **Degradation (Phase 2):** The injection of quantum noise causes a significant upward shift in the computed ground state energy, pushing the results well outside the threshold of chemical accuracy.
2. **Recovery (Phase 3):** Applying Zero Noise Extrapolation (ZNE) successfully mitigates the simulated hardware errors, bringing the final computed energies much closer to the ideal baseline without requiring additional physical qubits for quantum error correction.

*Here is a breakdown of exactly what information those numbers provide:* 
## 1. The Equilibrium Bond Length and Ground State (Chemistry Insight): 
By observing where the energy reaches its absolute lowest point (the global minimum) on the ideal curve, we obtain the natural resting distance between the two Hydrogen atoms. In the data, this occurs at ~0.735 Å with a ground state energy of -1.13728 Ha. This tells us the fundamental, stable geometry of the molecule. 

## 2. The Dissociation Energy (Chemistry Insight): 
As the distance increases beyond the equilibrium point (e.g., towards 2.00 Å), the energy rises and eventually plateaus. The difference between the lowest energy state and this plateau gives us the bond dissociation energy—the exact amount of energy required to permanently break the $H_2$ molecule apart into two isolated hydrogen atoms.

## 3. Quantification of Hardware Degradation (Algorithmic Insight): 
The Phase 2 (Noisy) results provide a direct measure of how decoherence, gate errors, and readout errors affect the VQE optimizer. Because the noisy energy values are consistently higher (closer to zero) than the ideal values, we learn that physical hardware errors prevent the quantum circuit from reaching the true mathematical minimum. It quantifies the "accuracy gap" inherent in current NISQ (Noisy Intermediate-Scale Quantum) devices.
  
##  4. The Efficacy of Error Mitigation (Algorithmic Insight): 
The Phase 3 (ZNE) results tell us how much of that hardware degradation is mathematically recoverable. By successfully pushing the energy values back down near the ideal baseline, the data proves that we can extract chemically meaningful results from imperfect hardware without waiting for fully fault-tolerant quantum computers.
