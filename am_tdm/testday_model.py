import os
import numpy as np
from scipy.special import legendre

from am_tdm.gibbs import Gibbs
from am_tdm.reml import REML
from am_tdm.renum import Renum


def remove_postgsf90_incompatible_options():
    """
    Some of the options used for the BLUPF90 analysis are incompatible with POSTGSF90. As such, those lines are removed
    so that POSTGSF90 can be used to estimate SNP effects and/or SNP p-values. Incompatible lines are related to
    accuracy estimates, pev-pec estimates, as well as standard errors estimates
    :return: None
    """
    with open('renf90.par') as f:
        lines = f.readlines()

    incompatible_options = ['OPTION sol se', 'OPTION store accuracy', 'OPTION store_pev_pec']

    filtered_lines = list(filter(lambda x: not [y for y in incompatible_options if y in x], lines))
    with open('renf90.par', 'w') as f:
        f.writelines(filtered_lines)


class TestDayModel:
    def __init__(self, data, animal_col, lactation_col, dim_col, fixed_effects, trait_cols, ped=None, inbreeding=False,
                 dim_range=(5, 310), fixed_degree=4, random_degree=2, genomic_data=None, snp_effects=False,
                 snp_p_values=False, ag_variance=None, res_variance=None, pe_variance=None, estimation_method='em-reml',
                 em_steps=10, reml_maxrounds=None, reml_conv=None, rounds=10000, burn_in=1000, sampling=10,
                 use_blupf90_modules=True, export_A=False, export_Ainv=False, export_G=False, export_Ginv=False,
                 export_Hinv=False, export_A22=False, export_A22inv=False):
        """
        Class used to implement the Test-Day Model with multiple traits and multiple fixed effects and variable DIM
        range
        :param data: dataframe containing animals' phenotypic data
        :param animal_col: the column in data containing the ids of the animal - can be given as a string or as a number
        :param lactation_col: used for test day model, represents the column in data which contains the lactation for
        each record, can be given as a string or as a number
        :param dim_col: used for test day model, represents the column in data which contains the DIM for each record,
        can be given as a string or as a number
        :param fixed_effects: the fixed effects, which are given as an Iterable. Fixed effects can refer to one column
        and can be either categorical or covariate, or refer to concatenation of multiple columns (which will be
        considered categorical). They can also be nested, either one column is nested based on another one, or each
        column for a concatenated effect is nested based on one column
        :param trait_cols: the columns in data associated to traits - the columns are given as an Iterable object and
        can be either strings or numbers
        :param ped: dataframe containing animals' pedigree data - it is mandatory that it has 3 columns, the first one
        being the animals' ID, the second one the ID of the sire and the third one the ID of the dam
        :param inbreeding: boolean parameter which tells whether inbreeding should be accounted for or not
        :param dim_range: used for test day model, a pair of numbers specifying the DIM interval (for example, (5, 310))
        :param fixed_degree: used for test day model, represents the degree of the fixed Legendre polynomial
        :param random_degree: used for test day model, represents the degree of the random Legendre polynomial
        :param genomic_data: dataframe containing animals' genotypic data, if available
        :param snp_effects: boolean parameter for computing SNP effects
        :param snp_p_values: boolean parameter for computing SNP p-values
        :param ag_variance: initial additive genetic variance, if it exists
        :param res_variance: initial residual variance, if it exists
        :param pe_variance: initial permanent genetic variance, if it exists
        :param estimation_method: can be any of 'em-reml', 'ai-reml', 'ai-em-reml' or 'gibbs'
        :param em_steps: number of initial EM-REML steps (used only if estimation_method='ai-em-reml')
        :param reml_maxrounds: option to set a maximum number of rounds for REML analysis. It applies only if
        estimation_method is 'em-reml', 'ai-reml' or 'ai-em-reml'
        :param reml_conv: option to set a convergence limit for REML analysis. It applies only if
        estimation_method is 'em-reml', 'ai-reml' or 'ai-em-reml'
        :param rounds: the number of total rounds of Gibbs sampling, used only if estimation_method = 'gibbs'
        :param burn_in: the number of burn in rounds, used only if estimation_method = 'gibbs'
        :param sampling: the sampling number (if sampling = n, each nth sample will be considered for the final
        estimate), used only if estimation_method = 'gibbs'
        :param use_blupf90_modules: whether or not to use BLUPF90 modules
        """

        self.estimation_method = estimation_method
        self.ag_variance = ag_variance
        self.res_variance = res_variance
        self.pe_variance = pe_variance
        self.use_blupf90_modules = use_blupf90_modules
        self.em_steps = em_steps
        self.reml_maxrounds = reml_maxrounds
        self.reml_conv = reml_conv
        self.rounds = rounds
        self.burn_in = burn_in
        self.sampling = sampling
        self.dim_range = dim_range
        self.fixed_degree = fixed_degree
        self.random_degree = random_degree
        self.degree = max(self.fixed_degree, self.random_degree)
        self.G = None
        self.P = None
        self.R = None
        self.fixed_effects = fixed_effects
        self.number_of_traits = len(trait_cols)
        self.genomic_data = genomic_data
        self.snp_effects = snp_effects
        self.snp_p_values = snp_p_values

        self.__check_genomic_options__()

        # Firstly, the pedigree is renumbered and reordered
        self.renum = Renum(data, animal_col, ped, inbreeding=inbreeding, genomic_data=genomic_data,
                           use_blupf90_modules=use_blupf90_modules, trait_cols=trait_cols, fixed_effects=fixed_effects,
                           res_variance=res_variance, ag_variance=ag_variance, pe_variance=pe_variance,
                           lactation_col=lactation_col, dim_col=dim_col, dim_range=dim_range, fixed_degree=fixed_degree,
                           random_degree=random_degree, export_A=export_A, export_Ainv=export_Ainv,
                           export_A22=export_A22, export_A22inv=export_A22inv, export_G=export_G,
                           export_Ginv=export_Ginv, export_Hinv=export_Hinv)

        self.FE = []
        self.fixed_curve_coefficients = np.zeros((self.renum.lactation_dim, self.number_of_traits,
                                                  self.fixed_degree + 1))
        self.fixed_curve_values = np.zeros((self.renum.lactation_dim, self.number_of_traits,
                                            dim_range[1] - dim_range[0] + 1))
        self.additive_coefficients = np.zeros((self.renum.lactation_dim, self.number_of_traits, self.renum.animal_count,
                                               self.random_degree + 1))
        self.permanent_coefficients = np.zeros((self.renum.lactation_dim, self.number_of_traits,
                                                self.renum.animal_count, self.random_degree + 1))
        self.EBVs = np.zeros((self.renum.lactation_dim, self.number_of_traits, self.renum.animal_count,
                              dim_range[1] - dim_range[0] + 1))
        self.PERMs = np.zeros((self.renum.lactation_dim, self.number_of_traits, self.renum.animal_count,
                               dim_range[1] - dim_range[0] + 1))
        self.heritabilities = np.zeros((self.renum.lactation_dim, self.number_of_traits,
                                        dim_range[1] - dim_range[0] + 1))
        self.repeatabilities = np.zeros((self.renum.lactation_dim, self.number_of_traits,
                                         dim_range[1] - dim_range[0] + 1))
        self.var_G = np.zeros((self.renum.lactation_dim, self.number_of_traits, dim_range[1] - dim_range[0] + 1))
        self.var_P = np.zeros((self.renum.lactation_dim, self.number_of_traits, dim_range[1] - dim_range[0] + 1))
        self.var_R = np.zeros((self.renum.lactation_dim, self.number_of_traits))
        self.PEVs = np.zeros((self.renum.lactation_dim, self.number_of_traits, self.renum.animal_count,
                              dim_range[1] - dim_range[0] + 1))
        self.RELs = np.zeros((self.renum.lactation_dim, self.number_of_traits, self.renum.animal_count,
                              dim_range[1] - dim_range[0] + 1))
        self.PEV_PECs = np.zeros((self.renum.animal_count, (self.random_degree + 1) * self.number_of_traits
                                  * self.renum.lactation_dim, (self.random_degree + 1) * self.number_of_traits
                                  * self.renum.lactation_dim))
        self.avg_heritabilities = np.zeros((self.renum.lactation_dim, self.number_of_traits))
        self.avg_repeatabilities = np.zeros((self.renum.lactation_dim, self.number_of_traits))
        self.avg_var_G = np.zeros((self.renum.lactation_dim, self.number_of_traits))
        self.avg_var_P = np.zeros((self.renum.lactation_dim, self.number_of_traits))
        self.avg_PEVs = np.zeros((self.renum.lactation_dim, self.number_of_traits, self.renum.animal_count))
        self.avg_RELs = np.zeros((self.renum.lactation_dim, self.number_of_traits, self.renum.animal_count))
        self.DRPs = np.zeros((self.renum.lactation_dim, self.number_of_traits, self.renum.animal_count))
        self.DRP_RELs = np.zeros((self.renum.lactation_dim, self.number_of_traits, self.renum.animal_count))
        self.DRP_weights = np.zeros((self.renum.lactation_dim, self.number_of_traits, self.renum.animal_count))

        if genomic_data is not None:
            self.snp_count = genomic_data.shape[1] - 1
        else:
            self.snp_count = 0
        self.genomic_data = genomic_data
        self.SNP_effects_coefficients = np.zeros((self.renum.lactation_dim, self.number_of_traits,
                                                  self.random_degree + 1, self.snp_count))
        self.SNP_p_values_coefficients = np.zeros((self.renum.lactation_dim, self.number_of_traits,
                                                   self.random_degree + 1, self.snp_count))
        self.SNP_effects = np.zeros((self.renum.lactation_dim, self.number_of_traits, dim_range[1] - dim_range[0] + 1,
                                     self.snp_count))
        self.SNP_p_values = np.zeros((self.renum.lactation_dim, self.number_of_traits, dim_range[1] - dim_range[0] + 1,
                                      self.snp_count))

        self.scaled_dim_range = np.arange(dim_range[0], dim_range[1] + 1)
        self.scaled_dim_range = -1 + 2 * (self.scaled_dim_range - dim_range[0]) / (dim_range[1] - dim_range[0])
        self.legendre_coefficients = np.zeros((dim_range[1] - dim_range[0] + 1, self.degree + 1))
        self.__add_legendre_coefficients__()
        self.legendre_random_coefficients = self.legendre_coefficients[:, range(random_degree + 1)]
        self.legendre_partial_sums = np.cumsum(self.legendre_coefficients, axis=0)
        self.legendre_random_sums = self.legendre_partial_sums[:, range(random_degree + 1)]

        if use_blupf90_modules:
            self.__estimate_parameters__()
            self.__add_updated_genetic_parameters__()
            self.__add_pev_pec__()
            self.__add_snp_effects__()
            os.system('blupf90 renf90.par')
            self.__read_blupf90_solutions__()
            self.__read_pev_pec__()

            if snp_effects or snp_p_values:
                remove_postgsf90_incompatible_options()
                os.system('postGSf90 renf90.par')
                self.__read_SNP_effects__()
                self.__read_SNP_p_values__()

                if snp_effects:
                    self.__compute_SNP_effects__()
                if snp_p_values:
                    self.__compute_SNP_p_values__()

        self.__compute_fixed_curve_values__()
        self.__compute_random_curves_values__()
        self.__compute_variances_and_heritabilities__()
        self.__compute_pevs_rels__()

        for i in range(self.renum.lactation_dim):
            for j in range(self.number_of_traits):
                self.__compute_DRPs__(i, j)

    def __estimate_parameters__(self):
        """
        Applies the chosen estimation method. Values of the additive genetic variance, residual variance and permanent
        environmental variance (if used) will be saved in fields of the current instance
        :return: None
        """
        self.variance_estimator = None
        if self.estimation_method == 'em-reml':
            self.variance_estimator = REML(data=self.renum.new_data, animal_col=self.renum.animal_col,
                                           ped=self.renum.new_ped, fixed_effects=self.renum.fixed_effects,
                                           Ainv=self.renum.Ainv, Geninv=self.renum.Ginv, Hinv=self.renum.Hinv,
                                           method='em', G_init=self.ag_variance, P_init=self.pe_variance,
                                           R_init=self.res_variance, use_blupf90_modules=self.use_blupf90_modules,
                                           fixed_degree=self.fixed_degree, random_degree=self.random_degree,
                                           maxrounds=self.reml_maxrounds, conv=self.reml_conv)
        elif self.estimation_method == 'ai-reml':
            self.variance_estimator = REML(data=self.renum.new_data, animal_col=self.renum.animal_col,
                                           ped=self.renum.new_ped, fixed_effects=self.renum.fixed_effects,
                                           Ainv=self.renum.Ainv, Geninv=self.renum.Ginv, Hinv=self.renum.Hinv,
                                           method='ai', G_init=self.ag_variance, P_init=self.pe_variance,
                                           R_init=self.res_variance, use_blupf90_modules=self.use_blupf90_modules,
                                           fixed_degree=self.fixed_degree, random_degree=self.random_degree,
                                           maxrounds=self.reml_maxrounds, conv=self.reml_conv)
        elif self.estimation_method == 'ai-em-reml':
            self.variance_estimator = REML(data=self.renum.new_data, animal_col=self.renum.animal_col,
                                           ped=self.renum.new_ped, fixed_effects=self.renum.fixed_effects,
                                           Ainv=self.renum.Ainv, Geninv=self.renum.Ginv, Hinv=self.renum.Hinv,
                                           method='ai-em', em_steps=self.em_steps, G_init=self.ag_variance,
                                           P_init=self.pe_variance, R_init=self.res_variance,
                                           use_blupf90_modules=self.use_blupf90_modules, fixed_degree=self.fixed_degree,
                                           random_degree=self.random_degree, maxrounds=self.reml_maxrounds,
                                           conv=self.reml_conv)
        elif self.estimation_method == 'gibbs':
            self.variance_estimator = Gibbs(data=self.renum.new_data, animal_col=self.renum.animal_col,
                                            ped=self.renum.new_ped, fixed_effects=self.renum.fixed_effects,
                                            Ainv=self.renum.Ainv, Geninv=self.renum.Ginv, Hinv=self.renum.Hinv,
                                            rounds=self.rounds, burn_in=self.burn_in, sampling=self.sampling,
                                            G_init=self.ag_variance, P_init=self.pe_variance, R_init=self.res_variance,
                                            use_blupf90_modules=self.use_blupf90_modules,
                                            fixed_degree=self.fixed_degree, random_degree=self.random_degree)
        elif self.estimation_method is not None:
            raise ValueError('Invalid genetic parameters estimation method')
        else:
            if (self.ag_variance is None) or (self.res_variance is None)\
                    or (self.pe_variance is None and self.renum.has_perm):
                raise ValueError('When not using an estimation method, genetic (co)variances should be given')
        if self.variance_estimator is not None:
            self.G = self.variance_estimator.G
            self.P = self.variance_estimator.P
            self.R = self.variance_estimator.R
        else:
            self.G = self.ag_variance
            self.P = self.pe_variance
            self.R = self.res_variance

    def __add_updated_genetic_parameters__(self):
        """
        When using BLUPF90, genetic, environmental and residual parameters need to be updated in the renf90.par file,
        because initially it contains dummy values. Having the parameters saved as fields, we iterate through each line
        of the file. When we reach a 'RANDOM_RESIDUAL VALUES', we will replace the next lines with the value of the
        residual (co)variances matrix. When we reach the first '(CO)VARIANCES' line, we will replace the next lines with
        the additive genetic (co)variances matrix, and finally, if we find a second '(CO)VARIANCES' line, we will
        replace the next lines with the permanent environmental (co)variances matrix
        :return: None
        """
        file_lines = []
        read_residual, read_additive, read_permanent = False, False, False
        residual_line, additive_line, permanent_line = 0, 0, 0
        with open('renf90.par') as f:
            line = f.readline()
            while line:
                if 'RANDOM_RESIDUAL VALUES' in line:
                    read_residual = True
                    file_lines.append(line)
                elif '(CO)VARIANCES' in line:
                    if additive_line > 0:
                        read_permanent = True
                    else:
                        read_additive = True
                    file_lines.append(line)
                elif read_residual:
                    file_lines.append(' '.join(map(str, self.R[residual_line])) + '\n')
                    residual_line += 1
                    if residual_line >= self.R.shape[0]:
                        read_residual = False
                        for _ in range(((self.R.shape[0] - 1) // 7) * self.R.shape[0]):
                            line = f.readline()
                elif read_additive:
                    file_lines.append(' '.join(map(str, self.G[additive_line])) + '\n')
                    additive_line += 1
                    if additive_line >= self.G.shape[0]:
                        read_additive = False
                        for _ in range(((self.G.shape[0] - 1) // 7) * self.G.shape[0]):
                            line = f.readline()
                elif read_permanent:
                    file_lines.append(' '.join(map(str, self.P[permanent_line])) + '\n')
                    permanent_line += 1
                    if permanent_line >= self.P.shape[0]:
                        read_permanent = False
                        for _ in range(((self.P.shape[0] - 1) // 7) * self.P.shape[0]):
                            line = f.readline()
                else:
                    file_lines.append(line)
                line = f.readline()
        with open('renf90.par', 'w') as f:
            f.writelines(file_lines)

    def __read_blupf90_solutions__(self):
        """
        Reads the solutions from the same named file generated by BLUPF90. For each trait, the first len(fixed_effects)
        effects will be the fixed effects solutions and thus, they will be added to the FE list. Otherwise, the effects
        from len(fixed_effects) + 1 to len(fixed_effects) + fixed_degree + 1 will represent the fixed lactation curve
        coefficients. The effects from len(fixed_effects) + fixed_degree + 2 to len(fixed_effects) + fixed_degree +
        random_degree + 2 will represent the random additive coefficients for each animal. Finally, the effects from
        len(fixed_effects) + fixed_degree + random_degree + 3 to len(fixed_effects) + fixed_degree + 2 * random_degree +
        3 will represent the random permanent enviromental coefficients for each animal.
        :return: None
        """
        with open('solutions') as f:
            # Ignores the first line, which is only a header
            line = f.readline()

            line = f.readline()
            while line:
                values = line.strip().split()
                trait = int(values[0])
                effect = int(values[1])
                level = int(values[2])
                solution = float(values[3])
                if effect <= len(self.fixed_effects):
                    self.FE.append(solution)
                else:
                    if effect <= len(self.fixed_effects) + self.fixed_degree + 1:
                        self.fixed_curve_coefficients[(trait - 1) // self.number_of_traits,
                                                      (trait - 1) % self.number_of_traits,
                                                      effect - len(self.fixed_effects) - 1] = solution
                    elif effect <= len(self.fixed_effects) + self.fixed_degree + self.random_degree + 2:
                        self.additive_coefficients[(trait - 1) // self.number_of_traits,
                                                   (trait - 1) % self.number_of_traits, level - 1,
                                                   effect - len(self.fixed_effects) - self.fixed_degree - 2] = solution
                    else:
                        self.permanent_coefficients[(trait - 1) // self.number_of_traits,
                                                    (trait - 1) % self.number_of_traits, level - 1,
                                                    effect - len(self.fixed_effects) - self.fixed_degree
                                                    - self.random_degree - 3] = solution
                line = f.readline()
            self.FE = np.array(self.FE)

    def __add_legendre_coefficients__(self):
        """
        Computes the Legendre polynomials values for all scaled days in the given DIM range, which will be used for
        both fixed and random lactation curves
        :return: None
        """
        for i in range(self.degree + 1):
            self.legendre_coefficients[:, i] = legendre(i)(self.scaled_dim_range) * np.sqrt(i + 0.5)

    def __compute_fixed_curve_values__(self):
        """
        Computes the fixed lactation curve values over the whole given DIM range
        :return: None
        """
        for i in range(self.renum.lactation_dim):
            for j in range(self.number_of_traits):
                self.fixed_curve_values[i, j, :] = self.legendre_partial_sums[:, range(self.fixed_degree + 1)]\
                                                   @ self.fixed_curve_coefficients[i, j, :].T

    def __compute_random_curves_values__(self):
        """
        Computes the random lactation curves values over the whole given DIM range, that is, the EBVs and permanent
        effects
        :return: None
        """
        for i in range(self.renum.lactation_dim):
            for j in range(self.number_of_traits):
                for k in range(self.renum.animal_count):
                    self.EBVs[i, j, k, :] = self.legendre_partial_sums[:, range(self.random_degree + 1)]\
                                            @ self.additive_coefficients[i, j, k, :]
                    self.PERMs[i, j, k, :] = self.legendre_partial_sums[
                                             :, range(self.random_degree + 1)] @ self.permanent_coefficients[i, j, k, :]

    def __compute_variances_and_heritabilities__(self):
        """
        Computes the genetic parameters from random regression solutions, along with heritabilities and repeatabilities
        for each pair of trait and lactation
        :return:
        """
        for i in range(self.number_of_traits * self.renum.lactation_dim):
            lactation = i // self.number_of_traits
            trait = i % self.number_of_traits
            min_idx = i * (self.random_degree + 1)
            max_idx = (i + 1) * (self.random_degree + 1)
            self.var_G[lactation, trait, :] = (self.legendre_random_coefficients
                                               @ self.G[min_idx:max_idx, min_idx:max_idx]
                                               @ self.legendre_random_coefficients.T).diagonal()
            self.var_P[lactation, trait, :] = (self.legendre_random_coefficients
                                               @ self.P[min_idx:max_idx, min_idx:max_idx]
                                               @ self.legendre_random_coefficients.T).diagonal()
            self.var_R[lactation, trait] = self.R[i, i]
            repeat_variance = self.var_G[lactation, trait, :] + self.var_P[lactation, trait, :]
            pheno_variance = repeat_variance + self.var_R[lactation, trait]
            self.heritabilities[lactation, trait, :] = self.var_G[lactation, trait, :] / pheno_variance
            self.repeatabilities[lactation, trait, :] = repeat_variance / pheno_variance
            self.avg_var_G = self.var_G.mean(axis=2)
            self.avg_var_P = self.var_P.mean(axis=2)
            self.avg_heritabilities = self.heritabilities.mean(axis=2)
            self.avg_repeatabilities = self.repeatabilities.mean(axis=2)

    def __read_pev_pec__(self):
        """
        Reads the solutions found in the pev_pec_bf90 file and computes the associated PEC matrices
        :return: None
        """
        with open('pev_pec_bf90') as f:
            for line in f.readlines():
                values = line.strip().split()
                animal = int(values[0]) - 1
                row = 0
                col = 0
                for elem in values[1:]:
                    self.PEV_PECs[animal, row, col] = float(elem)
                    if col == row:
                        col, row = 0, row + 1
                    else:
                        col += 1
                self.PEV_PECs[animal, :, :] += self.PEV_PECs[animal, :, :].T
                self.PEV_PECs[animal, range(self.PEV_PECs.shape[1]), range(self.PEV_PECs.shape[2])] /= 2

    def __compute_pevs_rels__(self):
        """
        Computes PEVs based on the PEV_PEC matrices and then computes reliabilities based on PEVs. Finally, computes
        PEVs and RELs averages on all DIM
        :return: None
        """
        for i in range(self.renum.lactation_dim * self.number_of_traits):
            lactation = i // self.number_of_traits
            trait = i % self.number_of_traits
            for j in range(self.renum.animal_count):
                pev_pec_block = self.PEV_PECs[j, i * (self.random_degree + 1):(i + 1) * (self.random_degree + 1),
                                i * (self.random_degree + 1):(i + 1) * (self.random_degree + 1)]
                self.PEVs[lactation, trait, j, :] = (self.legendre_random_coefficients @ pev_pec_block
                                                     @ self.legendre_random_coefficients.T).mean(axis=0)
                if self.renum.inbreeding:
                    self.RELs[lactation, trait, j, :] = 1 - self.PEVs[lactation, trait, j, :]\
                                                        / (self.var_G[lactation, trait, :]
                                                           * (1 + self.renum.inbreeding_coefficients[j]))
                else:
                    self.RELs[lactation, trait, j, :] = 1 - self.PEVs[lactation, trait, j, :]\
                                                        / self.var_G[lactation, trait, :]
        self.avg_PEVs = self.PEVs.mean(axis=3)
        self.avg_RELs = self.RELs.mean(axis=3)

    def __compute_DRPs__(self, lactation, trait):
        """
        Computes DRPs based on Garrick's article and based on the R implementation that can be found at
        https://github.com/camult/DRP
        :return:
        """
        r2_gm = (np.where(self.renum.sires > 0, self.avg_RELs[lactation, trait, self.renum.sires - 1], 0)
                 + np.where(self.renum.dams > 0, self.avg_RELs[lactation, trait, self.renum.dams - 1], 0)) / 4
        alfa = 1 / (0.5 - r2_gm)
        delta = (0.5 - r2_gm) / (1 - self.avg_RELs[lactation, trait, :])
        alfa_delta = (alfa ** 2) + (16 / delta)
        lambda_star = (1 - self.avg_heritabilities[lactation, trait]) / self.avg_heritabilities[
            lactation, trait]
        Zlgm_Zgm = lambda_star * (0.5 * alfa - 4) + 0.5 * lambda_star * np.sqrt(alfa_delta)
        Zli_Zi = delta * Zlgm_Zgm + 2 * lambda_star * (2 * delta - 1)
        r2i = 1 - lambda_star / (Zli_Zi + lambda_star)
        gm = (np.where(self.renum.sires > 0, self.EBVs[lactation, trait, self.renum.sires - 1, -1], 0)
              + np.where(self.renum.dams > 0, self.EBVs[lactation, trait, self.renum.dams - 1, -1], 0)) / 2
        y1 = -2 * lambda_star * gm + (Zli_Zi + 2 * lambda_star) * self.EBVs[lactation, trait, :, -1]
        DRP = y1 / Zli_Zi
        wi = (1 - self.avg_heritabilities[lactation, trait])\
             / ((0.5 + (1 - r2i) / r2i) * self.avg_heritabilities[lactation, trait])
        self.DRPs[lactation, trait, :] = np.where(wi > 0.0, DRP, 0.0)
        self.DRP_RELs[lactation, trait, :] = np.where(wi > 0.0, r2i, 0.0)
        self.DRP_weights[lactation, trait, :] = np.where(wi > 0.0, wi, 0.0)

    def __add_pev_pec__(self):
        """
        The random regression is ordered so that it follows after the fixed effects, the fixed Legendre polynomials
        effects and the animal effect, which explains the value used in the write function
        :return: None
        """
        with open('renf90.par', 'a') as f:
            f.write('OPTION store_pev_pec ' + str(len(self.fixed_effects) + self.fixed_degree + 2) + '\n')

    def __check_genomic_options__(self):
        """
        Checks that none of the snp_effects or snp_p_values options are True when having no genomic data
        :return:
        """
        if (self.snp_effects or self.snp_p_values) and self.genomic_data is None:
            raise ValueError("Can't have any SNP option True if no genomic data is provided")

    def __read_SNP_effects__(self):
        """
        Reads the snp_sol file created by postGSf90 and saves the SNP effects
        :return: None
        """
        if self.snp_effects:
            with open('snp_sol') as f:
                # Ignore the first header line
                line = f.readline()

                line = f.readline()
                while line:
                    values = line.split()
                    count = int(values[0])
                    lactation = (count - 1) // self.number_of_traits
                    trait = (count - 1) % self.number_of_traits
                    coef = int(values[1])
                    snp = int(values[2])
                    effect = float(values[5])
                    self.SNP_effects_coefficients[lactation, trait, coef - len(self.fixed_effects)
                                                  - self.fixed_degree - 2, snp - 1] = effect
                    line = f.readline()

    def __read_SNP_p_values__(self):
        """
        Reads the chrsnp_pval file created by postGSf90 and saves the SNP effects
        :return: None
        """
        if self.snp_p_values:
            with open('chrsnp_pval') as f:
                line = f.readline()
                while line:
                    values = line.split()
                    count = int(values[0])
                    lactation = (count - 1) // self.number_of_traits
                    trait = (count - 1) % self.number_of_traits
                    coef = int(values[1])
                    snp = int(values[3])
                    effect = float(values[2])
                    self.SNP_p_values_coefficients[lactation, trait, coef - len(self.fixed_effects)
                                                   - self.fixed_degree - 2, snp - 1] = 10 ** -effect
                    line = f.readline()

    def __add_snp_effects__(self):
        """
        Checks if p-values should be added and if so, writes the required line in the renf90.par file
        :return: None
        """
        if self.snp_p_values:
            with open('renf90.par', 'a') as f:
                f.write('OPTION snp_p_value\n')


    def __compute_SNP_effects__(self):
        """
        Computes SNP effects based on SNP coefficients across all lactations, traits and DIM
        :return: None
        """
        for i in range(self.renum.lactation_dim):
            for j in range(self.number_of_traits):
                for k in range(self.renum.animal_count):
                    self.SNP_effects = self.legendre_partial_sums[:, range(self.random_degree + 1)]\
                                       @ self.SNP_effects_coefficients

    def __compute_SNP_p_values__(self):
        """
        Computes SNP effects based on SNP coefficients across all lactations, traits and DIM
        :return: None
        """
        for i in range(self.renum.lactation_dim):
            for j in range(self.number_of_traits):
                for k in range(self.renum.animal_count):
                    self.SNP_p_values = self.legendre_partial_sums[:, range(self.random_degree + 1)]\
                                        @ self.SNP_p_values_coefficients
