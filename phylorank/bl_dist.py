###############################################################################
#                                                                             #
#    This program is free software: you can redistribute it and/or modify     #
#    it under the terms of the GNU General Public License as published by     #
#    the Free Software Foundation, either version 3 of the License, or        #
#    (at your option) any later version.                                      #
#                                                                             #
#    This program is distributed in the hope that it will be useful,          #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of           #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            #
#    GNU General Public License for more details.                             #
#                                                                             #
#    You should have received a copy of the GNU General Public License        #
#    along with this program. If not, see <http://www.gnu.org/licenses/>.     #
#                                                                             #
###############################################################################

import os
import sys
import logging
from collections import defaultdict, namedtuple

from phylorank.newick import parse_label
from phylorank.common import (get_phyla_lineages, filter_taxa_for_dist_inference)

from biolib.taxonomy import Taxonomy

import dendropy

from numpy import (mean as np_mean,
                   std as np_std,
                   arange as np_arange,
                   percentile as np_percentile)


class BranchLengthDistribution():
    """Calculate distribution of branch lengths at each taxonomic rank."""

    def __init__(self):
        """Initialize."""
        self.logger = logging.getLogger()
        
    def _dist_to_ancestor(self, child, ancestor):
        """Calculate distance from child node to ancestor node."""
        
        d = 0.0
        cur_node = child
        while cur_node != ancestor:
            d += cur_node.edge.length
            cur_node = cur_node.parent_node
        
        return d
        
    def _ancestor_multiple_taxa_at_rank(self, node, rank_prefix):
        """Find first ancestor that contains multiple named lineages at the specified rank."""
        
        parent = node.parent_node
        while True:
            taxa = []
            
            for node in parent.levelorder_iter():
                if node.label:
                    support, taxon_name, _auxiliary_info = parse_label(node.label)
                    
                    if taxon_name:
                        for taxon in [x.strip() for x in taxon_name.split(';')]:
                            if taxon.startswith(rank_prefix):
                                taxa.append(taxon)
                            
                if len(taxa) >= 2:
                    break
                    
            if len(taxa) >= 2:
                break  
        
            parent = parent.parent_node
            
        return parent
    
    def optimal(self, input_tree, rank, output_table):
        """Determine branch length for best congruency with existing taxonomy.

        Parameters
        ----------
        input_tree : str
            Name of input tree.
        rank : int
            Taxonomic rank to consider (1=Phylum, ..., 6=Species).
        output_table : str
            Name of output table.
        """
    
        # read tree
        self.logger.info('Reading tree.')
        tree = dendropy.Tree.get_from_path(input_tree,
                                            schema='newick',
                                            rooting='force-rooted',
                                            preserve_underscores=True)
        
        # get mean distance to terminal taxa for each node along with
        # other stats needed to determine classification
        self.logger.info('Determining MDTT for each node.')
        rank_prefix = Taxonomy.rank_prefixes[rank]
        child_rank_prefix = Taxonomy.rank_prefixes[rank+1]
        rank_info = []
        rank_dists = set()                                
        for node in tree.seed_node.preorder_internal_node_iter():
            if node == tree.seed_node:
                continue
                
            # check if node is at the specified rank
            node_taxon = None
            if node.label:
                support, taxon_name, _auxiliary_info = parse_label(node.label)
                
                if taxon_name:
                    for taxon in [x.strip() for x in taxon_name.split(';')]:
                        if taxon.startswith(rank_prefix):
                            node_taxon = taxon
                        
            if not node_taxon or node_taxon == 'p__Patescibacteria':
                continue
                
            # check that node has two descendants at the next rank
            child_rank_taxa = []
            for c in node.levelorder_iter():
                if c.label:
                    support, taxon_name, _auxiliary_info = parse_label(c.label)
                    
                    if taxon_name:
                        for taxon in [x.strip() for x in taxon_name.split(';')]:
                            if taxon.startswith(child_rank_prefix):
                                child_rank_taxa.append(taxon)
                            
                if len(child_rank_taxa) >= 2:
                    break
                    
            if len(child_rank_taxa) < 2:
                continue
                
            # get mean branch length to terminal taxa
            dists_to_tips = []
            for t in node.leaf_iter():
                dists_to_tips.append(self._dist_to_ancestor(t, node))
                
            node_dist = np_mean(dists_to_tips)
            
            # get mean branch length to terminal taxa for first ancestor spanning multiple phyla
            ancestor = self._ancestor_multiple_taxa_at_rank(node, rank_prefix)
            
            ancestor_dists_to_tips = []
            for t in ancestor.leaf_iter():
                ancestor_dists_to_tips.append(self._dist_to_ancestor(t, ancestor))
                
            ancestor_dist = np_mean(ancestor_dists_to_tips)
                    
            rank_info.append([node_dist, ancestor_dist, node_taxon])
            rank_dists.add(node_dist)
            
        self.logger.info('Calculating threshold from %d taxa.' % len(rank_info))
            
        fout = open('bl_optimal_taxa_dists.tsv' , 'w')
        for node_dist, ancestor_dist, node_taxon in rank_info:
            fout.write('%s\t%.3f\t%.3f\n' % (node_taxon, node_dist, ancestor_dist))
        fout.close()
                    
        # report number of correct and incorrect taxa for each threshold
        fout = open(output_table, 'w')
        fout.write('Threshold\tCorrect\tIncorrect\tPrecision\n')
        top_correct = 0
        top_incorrect = 0
        top_precision = 0
        for dist_threshold in sorted(rank_dists, reverse=True):
            correct = 0
            incorrect = 0
            for node_dist, ancestor_dist, node_taxon in rank_info:
                # check if node/edge would be collapsed at the given threshold
                if node_dist <= dist_threshold and ancestor_dist > dist_threshold:
                    correct += 1
                elif node_dist > dist_threshold:
                    incorrect += 1
                else:
                    incorrect += 1 # above ancestor with multiple taxa
         
            denominator = correct + incorrect
            if denominator:
                precision = float(correct) / denominator
            else:
                precision = 0
                    
            fout.write('%f\t%d\t%d\t%.3f\n' % (dist_threshold, correct, incorrect, precision))
            
            if precision > top_precision:
                top_correct = correct
                top_incorrect = incorrect
                top_precision = precision
                top_threshold = dist_threshold
                
        return top_threshold, top_correct, top_incorrect
            
    def table(self, input_tree, taxon_category_file, bl_step_size, output_table):
        """Produce table with number of lineage for increasing mean branch lengths

        Parameters
        ----------
        input_tree : str
            Name of input tree.
        taxon_category_file : str
            File indicating category for each taxon in the tree.
        bl_step_size : float
            Step size in table for mean branch length criterion.
        output_table : str
            Name of output table.
        """
        
        # get category for each taxon
        taxon_category = {}
        for line in open(taxon_category_file):
            line_split = line.strip().split('\t')
            taxon_category[line_split[0]] = line_split[1]

        # read tree
        tree = TreeNode.read(input_tree, convert_underscores=False)
        tree.assign_ids()
        
        # determine mean distance to leaves and taxon categories for each node
        all_categories = set()
        node_info = []
        parent_mean_dist_to_leafs = {}
        for node in tree.preorder():
            if node.is_tip():
                mean_dist_to_leafs = 0.0
                categories = set()
                for c in taxon_category[node.name].split('/'):
                    categories.add(c)
            else:
                dist_to_leafs = []
                categories = set()
                for t in node.tips():
                    dist_to_leafs.append(t.accumulate_to_ancestor(node))
                    
                    for c in taxon_category[t.name].split('/'):
                        categories.add(c)

                mean_dist_to_leafs = np_mean(dist_to_leafs)
                
            if node.parent:
                p = parent_mean_dist_to_leafs[node.parent.id]
            else:
                p = mean_dist_to_leafs + 1e-6

            category = '/'.join(sorted(list(categories), reverse=True))
            all_categories.add(category)
            node_info.append([mean_dist_to_leafs, p, category])  
            parent_mean_dist_to_leafs[node.id] = mean_dist_to_leafs
            
        # write table
        fout = open(output_table, 'w')
        fout.write('Threshold')
        for c in all_categories:
            fout.write('\t%s' % c)
        fout.write('\n')
        
        node_info.sort()
        for bl_threshold in np_arange(0, node_info[-1][0] + bl_step_size, bl_step_size):
            category_count = defaultdict(int)
            for mean_bl_dist, parent_mean_bl_dist, category in node_info:
                if bl_threshold >= mean_bl_dist and bl_threshold < parent_mean_bl_dist:
                    category_count[category] += 1
                    
            if sum(category_count.values()) > 0:
                fout.write('%.3f' % bl_threshold)
                for c in all_categories:
                    fout.write('\t%d' % category_count[c])
                fout.write('\n')
        fout.close()
        
    def decorate(self, 
                    input_tree,
                    taxonomy_file,
                    threshold, 
                    rank, 
                    retain_named_lineages, 
                    keep_labels,
                    prune,
                    output_tree):
        """Produce table with number of lineage for increasing mean branch lengths

        Parameters
        ----------
        input_tree : str
            Name of input tree.
        taxonomy_file : str
            File with taxonomic information for each taxon.
        threshold : float
            Branch length threshold.
        rank : int
            Rank of labels to retain on tree.
        retain_named_lineages : bool
            Retain existing named lineages at the specified rank.
        keep_labels : bool
            Keep existing labels on tree.
        prune : bool
            Prune tree to preserve only the shallowest and deepest taxa in each lineage.
        output_tree : str
            Name of output tree.
        """
        
        # read taxonomy
        taxonomy = Taxonomy().read(taxonomy_file)
        
        # read tree
        self.logger.info('Reading tree.')
        tree = dendropy.Tree.get_from_path(input_tree,
                                            schema='newick',
                                            rooting='force-rooted',
                                            preserve_underscores=True)
        
        # decorate tree
        rank_prefix = Taxonomy.rank_prefixes[rank]
        new_name_number = defaultdict(int)
        ncbi_only = 0
        sra_only = 0
        
        labeled_nodes = set()
        
        stack = [tree.seed_node]
        while stack:
            node = stack.pop()
            
            # check if node is a leaf
            if node.is_leaf():
                continue
                
            # check if ancestor already has a label at this rank
            p = node
            parent_taxon = None
            while p and not parent_taxon:
                if p.label:
                    support, taxon_name, _auxiliary_info = parse_label(p.label)
                    
                    if taxon_name:
                        for taxon in [x.strip() for x in taxon_name.split(';')]:
                            if taxon.startswith(rank_prefix):
                                parent_taxon = taxon
                    
                p = p.parent_node
                    
            if retain_named_lineages and parent_taxon:
                for c in node.child_node_iter():
                    stack.append(c)
                continue
                
            # check if descendant node already has a label at this rank
            children_taxon = []
            for c in node.preorder_internal_node_iter():
                if c.label:
                    support, taxon_name, _auxiliary_info = parse_label(c.label)
                    
                    if taxon_name:
                        for taxon in [x.strip() for x in taxon_name.split(';')]:
                            if taxon.startswith(rank_prefix):
                                children_taxon.append(taxon)
                        
            if retain_named_lineages and children_taxon:
                for c in node.child_node_iter():
                    stack.append(c)
                continue
                
            # check if node meets mean branch length criterion
            dists_to_tips = []
            for t in node.leaf_iter():
                dists_to_tips.append(self._dist_to_ancestor(t, node))
                
            if np_mean(dists_to_tips) > threshold:
                for c in node.child_node_iter():
                    stack.append(c)
                continue
                                
            # count number of SRA and NCBI taxa below node
            num_sra_taxa = 0
            num_ncbi_taxa = 0
            taxa_labels = set()
            for t in node.leaf_iter():
                if t.taxon.label.startswith('U_'):
                    num_sra_taxa += 1
                else:
                    num_ncbi_taxa += 1
                    
                t = taxonomy[t.taxon.label]
                taxon = t[rank][3:].replace('Candidatus ', '')
                if taxon:
                    taxa_labels.add(taxon)
                    
            if parent_taxon:
                taxa_labels.add(parent_taxon[3:].replace('Candidatus ', ''))
            elif children_taxon:
                for c in children_taxon:
                    taxa_labels.add(c[3:].replace('Candidatus ', ''))
            
                    
            # name lineage based on position to existing named lineages
            if taxa_labels:
                lineage_name = ', '.join(sorted(taxa_labels))
            else:
                lineage_name = 'Unclassified lineage'
            
            support = None
            taxon_name = None
            if node.label: # preserve support information
                support, _taxon_name, _auxiliary_info = parse_label(node.label)

            new_name_number[lineage_name] += 1

            if support:
                node.label = '%d:%s %d SRA%d_NCBI%d' % (support,
                                                            lineage_name,
                                                            new_name_number[lineage_name],
                                                            num_sra_taxa, 
                                                            num_ncbi_taxa)
            else:    
                node.label = '%s %d SRA%d_NCBI%d' % (lineage_name,
                                                        new_name_number[lineage_name],
                                                        num_sra_taxa, 
                                                        num_ncbi_taxa)
                                                        
            labeled_nodes.add(node)
                 
            if num_sra_taxa == 0:
                ncbi_only += 1
            if num_ncbi_taxa == 0:
                sra_only += 1
                
        # strip previous labels
        if not keep_labels:
            for node in tree.preorder_internal_node_iter():
                if node in labeled_nodes:
                    continue
                    
                if node.label: # preserve support information
                    support, _taxon_name, _auxiliary_info = parse_label(node.label)
                    node.label = support
                    
        # prune tree to shallowest and deepest taxa in each named lineage
        if prune:
            nodes_to_prune = set()
            for node in labeled_nodes:
                for c in node.child_node_iter():
                    dists = []
                    for t in c.leaf_iter():
                        d = self._dist_to_ancestor(t, node)
                        dists.append((d, t))
                    
                    dists.sort()
                    
                    # select taxa at the 10th and 90th percentiles to
                    # give a good sense of the range of depths
                    perc_10th_index = int(0.1 * len(dists) + 0.5)
                    perc_90th_index = int(0.9 * len(dists) + 0.5)
                    for i, (d, t) in enumerate(dists):
                        if i != perc_10th_index and i != perc_90th_index:
                            nodes_to_prune.add(t.taxon)
                
            print 'before prune', sum([1 for _ in tree.leaf_node_iter()])
            tree.prune_taxa(nodes_to_prune)
            print 'after prune', sum([1 for _ in tree.leaf_node_iter()])
                        
        self.logger.info('Decorated %d nodes.' % sum(new_name_number.values()))
        self.logger.info('NCBI-only %d; SRA-only %d' % (ncbi_only, sra_only))
        
        tree.write_to_path(output_tree, schema='newick', suppress_rooting=True, unquoted_underscores=True)

    def run(self, input_tree, trusted_taxa_file, min_children, taxonomy_file, output_dir):
        """Calculate distribution of branch lengths at each taxonomic rank.

        Parameters
        ----------
        input_tree : str
            Name of input tree.
        trusted_taxa_file : str
            File specifying trusted taxa to consider when inferring distribution. Set to None to consider all taxa.
        min_children : int
            Only consider taxa with at least the specified number of children taxa when inferring distribution.
        taxonomy_file : str
            File containing taxonomic information for leaf nodes (if NULL, read taxonomy from tree).
        output_dir : str
            Desired output directory.
        """

        tree = dendropy.Tree.get_from_path(input_tree, 
                                            schema='newick', 
                                            rooting='force-rooted', 
                                            preserve_underscores=True)
        
        # pull taxonomy from tree
        if not taxonomy_file:
            self.logger.info('Reading taxonomy from tree.')
            taxonomy_file = os.path.join(output_dir, 'taxonomy.tsv')
            taxonomy = Taxonomy().read_from_tree(input_tree)
            Taxonomy().write(taxonomy, taxonomy_file)
        else:
            self.logger.info('Reading taxonomy from file.')
            taxonomy = Taxonomy().read(taxonomy_file)
            
        # read trusted taxa
        trusted_taxa = None
        if trusted_taxa_file:
            trusted_taxa = read_taxa_file(trusted_taxa_file)
        
        # determine taxa to be used for inferring distribution
        taxa_for_dist_inference = filter_taxa_for_dist_inference(tree, taxonomy, set(), min_children, -1)
        
        # determine branch lengths to leaves for named lineages
        rank_bl_dist = defaultdict(list)
        taxa_bl_dist = defaultdict(list)
        taxa_at_rank = defaultdict(list)
        for node in tree.postorder_node_iter():
            if node.is_leaf() or not node.label:
                continue
                
            _support, taxon, _auxiliary_info = parse_label(node.label)
            if not taxon:
                continue
                
            # get most specific rank in multi-rank taxa string
            taxa = [t.strip() for t in taxon.split(';')]
            taxon = taxa[-1]
            
            most_specific_rank = taxon[0:3]
            taxa_at_rank[Taxonomy.rank_index[most_specific_rank]].append(taxon)
                
            for n in node.leaf_iter():
                dist_to_node = 0
                while n != node:
                    dist_to_node += n.edge_length
                    n = n.parent_node
                
                for t in taxa:
                    taxa_bl_dist[t].append(dist_to_node)

            rank = Taxonomy.rank_labels[Taxonomy.rank_index[most_specific_rank]]
            if rank != 'species' or Taxonomy().validate_species_name(taxon):
                if taxon in taxa_for_dist_inference:
                    rank_bl_dist[rank].append(np_mean(taxa_bl_dist[taxon]))
                            
        # report number of taxa at each rank
        print ''
        print 'Rank\tTaxa\tTaxa for Inference'
        for rank, taxa in taxa_at_rank.iteritems():
            taxa_for_inference = [x for x in taxa if x in taxa_for_dist_inference]
            print '%s\t%d\t%d' % (Taxonomy.rank_labels[rank], len(taxa), len(taxa_for_inference))
        print ''
                    
        # report results sorted by rank
        sorted_taxon = []
        for rank_prefix in Taxonomy.rank_prefixes:
            taxa_at_rank = []
            for taxon in taxa_bl_dist:
                if taxon.startswith(rank_prefix):
                    taxa_at_rank.append(taxon)
                    
            sorted_taxon += sorted(taxa_at_rank)
                
        # report results for each named group
        taxa_file = os.path.join(output_dir, 'taxa_bl_dist.tsv')
        fout = open(taxa_file, 'w')
        fout.write('Taxa\tUsed for Inference\tMean\tStd\t5th\t10th\t50th\t90th\t95th\n')
        for taxon in sorted_taxon:
            dist = taxa_bl_dist[taxon]

            p = np_percentile(dist, [5, 10, 50, 90, 95])
            fout.write('%s\t%s\t%g\t%g\t%g\t%g\t%g\t%g\t%g\n' % (taxon,
                                                                str(taxon in taxa_for_dist_inference),
                                                                np_mean(dist),
                                                                np_std(dist),
                                                                p[0], p[1], p[2], p[3], p[4]))
        fout.close()
        
        # report results for each taxonomic rank
        rank_file = os.path.join(output_dir, 'rank_bl_dist.tsv')
        fout = open(rank_file, 'w')
        fout.write('Rank\tMean\tStd\t5th\t10th\t50th\t90th\t95th\n')
        for rank in Taxonomy.rank_labels:
            dist = rank_bl_dist[rank]
            p = np_percentile(dist, [5, 10, 50, 90, 95])
            fout.write('%s\t%g\t%g\t%g\t%g\t%g\t%g\t%g\n' % (rank,
                                                                np_mean(dist),
                                                                np_std(dist),
                                                                p[0], p[1], p[2], p[3], p[4]))
        fout.close()
        