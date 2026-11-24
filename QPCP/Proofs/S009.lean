import QPCP.Statements

namespace QPCP.Proof.S009

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

theorem mul_zero_union {n : ℕ} {S T : Finset (Fin n)} {A B : Op n} (hA : ActsOn S A)
    (hB : ActsOn T B) {x y : Config n} (h : ¬ AgreeOff (S ∪ T) x y) : (A * B) x y = 0 := by
  rw [Matrix.mul_apply]
  refine Finset.sum_eq_zero (fun z _ => ?_)
  by_cases hxz : AgreeOff S x z
  · have hzy : ¬ AgreeOff T z y := fun hzy => h (fun i hi =>
      (hxz i (fun hS => hi (Finset.mem_union_left _ hS))).trans
        (hzy i (fun hT => hi (Finset.mem_union_right _ hT))))
    rw [zero_of hB hzy, mul_zero]
  · rw [zero_of hA hxz, zero_mul]

/-- The sum defining `(A * B) x y` collapses to the single term at `glue`-like `z`. -/
theorem mul_single {n : ℕ} {S T : Finset (Fin n)} {A B : Op n} (hdis : Disjoint S T)
    (hA : ActsOn S A) (hB : ActsOn T B) (x y : Config n) :
    (A * B) x y = A x (fun i => if i ∈ S then y i else x i) *
      B (fun i => if i ∈ S then y i else x i) y := by
  rw [Matrix.mul_apply]
  refine Finset.sum_eq_single _ (fun z' _ hne => ?_) (fun h => absurd (Finset.mem_univ _) h)
  by_contra hne'
  have h1 : AgreeOff S x z' := by
    by_contra h1
    exact hne' (by rw [zero_of hA h1, zero_mul])
  have h2 : AgreeOff T z' y := by
    by_contra h2
    exact hne' (by rw [zero_of hB h2, mul_zero])
  apply hne
  funext i
  by_cases hi : i ∈ S
  · have hT : i ∉ T := Finset.disjoint_left.1 hdis hi
    simp only [hi, ite_true]
    exact h2 i hT
  · simp only [hi, ite_false]
    exact (h1 i hi).symm

theorem comm {n : ℕ} {S T : Finset (Fin n)} {A B : Op n} (hdis : Disjoint S T)
    (hA : ActsOn S A) (hB : ActsOn T B) : Commute A B := by
  ext x y
  by_cases h : AgreeOff (S ∪ T) x y
  · rw [mul_single hdis hA hB x y, mul_single hdis.symm hB hA x y]
    have e1 : A x (fun i => if i ∈ S then y i else x i) =
        A (fun i => if i ∈ T then y i else x i) y := by
      refine acts_congr hA ?_ ?_ ⟨fun _ i hi => ?_, fun _ i hi => ?_⟩
      · funext i
        simp [restrict, Finset.disjoint_left.1 hdis i.2]
      · funext i
        simp [restrict, i.2]
      · by_cases hT : i ∈ T
        · simp [hT]
        · simp only [hT, ite_false]
          exact h i (by simp [hi, hT])
      · simp [hi]
    have e2 : B (fun i => if i ∈ S then y i else x i) y =
        B x (fun i => if i ∈ T then y i else x i) := by
      refine acts_congr hB ?_ ?_ ⟨fun _ i hi => ?_, fun _ i hi => ?_⟩
      · funext i
        simp [restrict, Finset.disjoint_right.1 hdis i.2]
      · funext i
        simp [restrict, i.2]
      · simp [hi]
      · by_cases hS : i ∈ S
        · simp [hS]
        · simp only [hS, ite_false]
          exact h i (by simp [hi, hS])
    rw [e1, e2, mul_comm]
  · rw [mul_zero_union hA hB h, mul_zero_union hB hA (by rwa [Finset.union_comm])]

end QPCP.Proof.S009

namespace QPCP.Proof

theorem S009 : QPCP.Statement.S009 := by
  intro n S T A B hdis hA hB
  exact QPCP.Proof.S009.comm hdis hA hB

end QPCP.Proof
