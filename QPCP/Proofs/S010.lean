import QPCP.Statements

namespace QPCP.Proof.S010

open QPCP Matrix

/-- The configuration equal to `s` on `S` and to `x` off `S`. -/
def glue {n : ℕ} (S : Finset (Fin n)) (x : Config n) (s : SubConfig S) : Config n :=
  fun i => if h : i ∈ S then s ⟨i, h⟩ else x i

theorem acts_congr {n : ℕ} {S : Finset (Fin n)} {A : Op n} (hA : ActsOn S A)
    {x y x' y' : Config n} (hx : restrict S x = restrict S x')
    (hy : restrict S y = restrict S y') (hxy : AgreeOff S x y ↔ AgreeOff S x' y') :
    A x y = A x' y' := by
  obtain ⟨a, ha⟩ := hA
  by_cases h : AgreeOff S x y
  · rw [(ha x y).1 h, (ha x' y').1 (hxy.1 h), hx, hy]
  · rw [(ha x y).2 h, (ha x' y').2 (fun h' => h (hxy.2 h'))]

theorem zero_of {n : ℕ} {S : Finset (Fin n)} {A : Op n} (hA : ActsOn S A)
    {x y : Config n} (h : ¬ AgreeOff S x y) : A x y = 0 := by
  obtain ⟨a, ha⟩ := hA
  exact (ha x y).2 h

theorem restrict_add {n : ℕ} {S : Finset (Fin n)} {x d : Config n}
    (hd : ∀ i ∈ S, d i = 0) : restrict S (x + d) = restrict S x := by
  funext i
  simp [restrict, hd i.1 i.2]

theorem agreeOff_add {n : ℕ} {S : Finset (Fin n)} {x y d : Config n} :
    AgreeOff S (x + d) (y + d) ↔ AgreeOff S x y := by
  simp [AgreeOff]

theorem shift {n : ℕ} {S : Finset (Fin n)} {A : Op n} (hA : ActsOn S A)
    {x y d : Config n} (hd : ∀ i ∈ S, d i = 0) : A (x + d) (y + d) = A x y :=
  acts_congr hA (restrict_add hd) (restrict_add hd) agreeOff_add

theorem of_shift {n : ℕ} {S : Finset (Fin n)} {A : Op n}
    (hZ : ∀ x y : Config n, ¬ AgreeOff S x y → A x y = 0)
    (hS : ∀ x y d : Config n, (∀ i ∈ S, d i = 0) → A (x + d) (y + d) = A x y) :
    ActsOn S A := by
  refine ⟨fun u v => A (glue S 0 u) (glue S 0 v), fun x y => ⟨fun h => ?_, hZ x y⟩⟩
  show A x y = A (glue S 0 (restrict S x)) (glue S 0 (restrict S y))
  have hd : ∀ i ∈ S, (x - glue S 0 (restrict S x)) i = 0 := by
    intro i hi
    simp [glue, restrict, hi]
  have h1 : glue S 0 (restrict S x) + (x - glue S 0 (restrict S x)) = x := by
    abel
  have h2 : glue S 0 (restrict S y) + (x - glue S 0 (restrict S x)) = y := by
    funext i
    by_cases hi : i ∈ S
    · simp [glue, restrict, hi]
    · simp [glue, hi, h i hi]
  have := hS (glue S 0 (restrict S x)) (glue S 0 (restrict S y)) _ hd
  rw [h1, h2] at this
  exact this

theorem mul {n : ℕ} {S : Finset (Fin n)} {A B : Op n} (hA : ActsOn S A)
    (hB : ActsOn S B) : ActsOn S (A * B) := by
  refine of_shift (fun x y h => ?_) (fun x y d hd => ?_)
  · rw [Matrix.mul_apply]
    refine Finset.sum_eq_zero (fun z _ => ?_)
    by_cases hxz : AgreeOff S x z
    · have hzy : ¬ AgreeOff S z y := fun hzy => h (fun i hi => (hxz i hi).trans (hzy i hi))
      rw [zero_of hB hzy, mul_zero]
    · rw [zero_of hA hxz, zero_mul]
  · rw [Matrix.mul_apply, Matrix.mul_apply]
    refine (Fintype.sum_equiv (Equiv.addRight d) _ _ (fun z => ?_)).symm
    simp only [Equiv.coe_addRight]
    rw [shift hA hd, shift hB hd]

theorem mono {n : ℕ} {S T : Finset (Fin n)} {A : Op n} (hST : S ⊆ T)
    (hA : ActsOn S A) : ActsOn T A := by
  refine of_shift (fun x y h => zero_of hA (fun h' => h (fun i hi => h' i
    (fun hS => hi (hST hS))))) (fun x y d hd => shift hA (fun i hi => hd i (hST hi)))

end QPCP.Proof.S010

namespace QPCP.Proof

theorem S010 : QPCP.Statement.S010 := by
  intro n S T A B hA hB
  exact QPCP.Proof.S010.mul (QPCP.Proof.S010.mono Finset.subset_union_left hA)
    (QPCP.Proof.S010.mono Finset.subset_union_right hB)

end QPCP.Proof
