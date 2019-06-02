/*
    This file is part of Leela Zero.
    Copyright (C) 2017-2019 Gian-Carlo Pascutto

    Leela Zero is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    Leela Zero is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with Leela Zero.  If not, see <http://www.gnu.org/licenses/>.

    Additional permission under GNU GPL version 3 section 7

    If you modify this Program, or any covered work, by linking or
    combining it with NVIDIA Corporation's libraries from the
    NVIDIA CUDA Toolkit and/or the NVIDIA CUDA Deep Neural
    Network library and/or the NVIDIA TensorRT inference library
    (or a modified version of those libraries), containing parts covered
    by the terms of the respective license agreement, the licensors of
    this Program grant you additional permission to convey the resulting
    work.
*/

#include "config.h"

#include <cassert>
#include <cstdio>
#include <cstdint>
#include <algorithm>
#include <cmath>
#include <functional>
#include <iterator>
#include <limits>
#include <numeric>
#include <random>
#include <utility>
#include <vector>

#include "UCTNode.h"
#include "FastBoard.h"
#include "FastState.h"
#include "GTP.h"
#include "GameState.h"
#include "Network.h"
#include "Utils.h"
#include "Random.h"


using namespace Utils;

UCTNode::UCTNode(int vertex, float policy) : m_move(vertex), m_policy(policy) {
}

bool UCTNode::first_visit() const {
    return m_visits == 0;
}

// Draw a slot from a pdf (an array of floats summing to 1).
// Anything less than alpha * max gets zeroed out.
//----------------------------------------------------------
int draw_slot( std::array<float,361> pdf, float alpha) {
  // Get the probs closer together
  auto all = std::vector<float>{};
  for (unsigned i=0; i < pdf.size(); i++) {
    all.push_back( pow( pdf[i], 0.33));
  }
  auto mmax = *std::max_element( all.begin(), all.end());
  // Zero out the bad ones
  float ssum = 0.0;
  for (unsigned i=0; i < all.size(); i++) {
    if (all[i] < mmax * alpha) {
      all[i] = 0.0;
    }
    else {
      ssum += all[i];
    }
  } // for
  // Rescale so the sum is 1.0
  for (unsigned i=0; i < all.size(); i++) {
    all[i] *= 1.0 / ssum;
  }
  // Draw
  float r = rand() / (float) RAND_MAX;
  ssum = 0.0;
  for (unsigned i=0; i < all.size(); i++) {
    ssum += all[i];
    if (ssum >= r) {
      return i;
    }
  } // for
  return  all.size() - 1;
} // draw_slot()

// Pick any slot from an array where log(arr[i]) > alpha * max.
//----------------------------------------------------------
int pick_any( std::array<float,361> pdf, float alpha) {
  auto all = std::vector<float>{};
  for (unsigned i=0; i < pdf.size(); i++) {
    all.push_back( pow( pdf[i], 0.33));
  }
  auto mmax = *std::max_element( all.begin(), all.end());
  // Zero out the bad ones
  auto good = std::vector<float>{};
  for (unsigned i=0; i < all.size(); i++) {
    if (all[i] > mmax * alpha) {
      good.push_back( i);
    }
  } // for
  // Draw
  float ridx = rand() % good.size();
  std::cout << ">>>>>> policy dist:\n";
  for (auto& p : all) {
    std::cout << p << ", ";
  }
  std::cout << "\n";
  std::cout << ">>> picked " << good[ridx] << " (idx " << ridx
            << ") out of " << good.size() << std::endl;
  return good[ridx];
} // pick_any()


// Swap the best intersection prob with another one that is close.
//-----------------------------------------------------------------------
void UCTNode::ahn_add_noise( Network::Netresult& netres, float alpha) {
  auto &x = netres.policy;
  auto idx = draw_slot( x, alpha);
  //auto idx = pick_any( x, 0.5);
  int argMax = std::distance( x.begin(), std::max_element(x.begin(), x.end()));
  auto mmax = x[argMax];
  std::cout << ">>>>> swapping max " << mmax << " and " << x[idx] << std::endl;
  x[argMax] = x[idx];
  x[idx] = mmax;
} // ahn_add_noise()

//--------------------------------------------------------------
bool UCTNode::create_children(Network & network,
                              std::atomic<int>& nodecount,
                              GameState& state,
                              float& eval,
                              float min_psa_ratio,
                              float ahn_randomness) {
    // no successors in final state
    if (state.get_passes() >= 2) {
        return false;
    }

    // acquire the lock
    if (!acquire_expanding()) {
        return false;
    }

    // can we actually expand?
    if (!expandable(min_psa_ratio)) {
        expand_done();
        return false;
    }

    auto raw_netlist = network.get_output(
        &state, Network::Ensemble::RANDOM_SYMMETRY);

    if (ahn_randomness != 0.0) {
      ahn_add_noise( raw_netlist, ahn_randomness);
    }

    // DCNN returns winrate as side to move
    const auto stm_eval = raw_netlist.winrate;
    const auto to_move = state.board.get_to_move();
    // our search functions evaluate from black's point of view
    if (to_move == FastBoard::WHITE) {
        m_net_eval = 1.0f - stm_eval;
    } else {
        m_net_eval = stm_eval;
    }
    eval = m_net_eval;

    std::vector<Network::PolicyVertexPair> nodelist;

    auto legal_sum = 0.0f;
    for (auto i = 0; i < NUM_INTERSECTIONS; i++) {
        const auto x = i % BOARD_SIZE;
        const auto y = i / BOARD_SIZE;
        const auto vertex = state.board.get_vertex(x, y);
        if (state.is_move_legal(to_move, vertex)) {
            nodelist.emplace_back(raw_netlist.policy[i], vertex);
            legal_sum += raw_netlist.policy[i];
        }
    }

    // Always try passes if we're not trying to be clever.
    auto allow_pass = cfg_dumbpass;

    // Less than 20 available intersections in a 19x19 game.
    if (nodelist.size() <= std::max(5, BOARD_SIZE)) {
        allow_pass = true;
    }

    // If we're clever, only try passing if we're winning on the
    // net score and on the board count.
    if (!allow_pass && stm_eval > 0.8f) {
        const auto relative_score =
            (to_move == FastBoard::BLACK ? 1 : -1) * state.final_score();
        if (relative_score >= 0) {
            allow_pass = true;
        }
    }

    if (allow_pass) {
        nodelist.emplace_back(raw_netlist.policy_pass, FastBoard::PASS);
        legal_sum += raw_netlist.policy_pass;
    }

    if (legal_sum > std::numeric_limits<float>::min()) {
        // re-normalize after removing illegal moves.
        for (auto& node : nodelist) {
            node.first /= legal_sum;
        }
    } else {
        // This can happen with new randomized nets.
        auto uniform_prob = 1.0f / nodelist.size();
        for (auto& node : nodelist) {
            node.first = uniform_prob;
        }
    }

    link_nodelist(nodecount, nodelist, min_psa_ratio);
    expand_done();
    return true;
}

void UCTNode::link_nodelist(std::atomic<int>& nodecount,
                            std::vector<Network::PolicyVertexPair>& nodelist,
                            float min_psa_ratio) {
    assert(min_psa_ratio < m_min_psa_ratio_children);

    if (nodelist.empty()) {
        return;
    }

    // Use best to worst order, so highest go first
    std::stable_sort(rbegin(nodelist), rend(nodelist));

    const auto max_psa = nodelist[0].first;
    const auto old_min_psa = max_psa * m_min_psa_ratio_children;
    const auto new_min_psa = max_psa * min_psa_ratio;
    if (new_min_psa > 0.0f) {
        m_children.reserve(
            std::count_if(cbegin(nodelist), cend(nodelist),
                [=](const auto& node) { return node.first >= new_min_psa; }
            )
        );
    } else {
        m_children.reserve(nodelist.size());
    }

    auto skipped_children = false;
    for (const auto& node : nodelist) {
        if (node.first < new_min_psa) {
            skipped_children = true;
        } else if (node.first < old_min_psa) {
            m_children.emplace_back(node.second, node.first);
            ++nodecount;
        }
    }

    m_min_psa_ratio_children = skipped_children ? min_psa_ratio : 0.0f;
}

const std::vector<UCTNodePointer>& UCTNode::get_children() const {
    return m_children;
}


int UCTNode::get_move() const {
    return m_move;
}

void UCTNode::virtual_loss() {
    m_virtual_loss += VIRTUAL_LOSS_COUNT;
}

void UCTNode::virtual_loss_undo() {
    m_virtual_loss -= VIRTUAL_LOSS_COUNT;
}

void UCTNode::update(float eval) {
    // Cache values to avoid race conditions.
    auto old_eval = static_cast<float>(m_blackevals);
    auto old_visits = static_cast<int>(m_visits);
    auto old_delta = old_visits > 0 ? eval - old_eval / old_visits : 0.0f;
    m_visits++;
    accumulate_eval(eval);
    auto new_delta = eval - (old_eval + eval) / (old_visits + 1);
    // Welford's online algorithm for calculating variance.
    auto delta = old_delta * new_delta;
    atomic_add(m_squared_eval_diff, delta);
}

bool UCTNode::has_children() const {
    return m_min_psa_ratio_children <= 1.0f;
}

bool UCTNode::expandable(const float min_psa_ratio) const {
#ifndef NDEBUG
    if (m_min_psa_ratio_children == 0.0f) {
        // If we figured out that we are fully expandable
        // it is impossible that we stay in INITIAL state.
        assert(m_expand_state.load() != ExpandState::INITIAL);
    }
#endif
    return min_psa_ratio < m_min_psa_ratio_children;
}

float UCTNode::get_policy() const {
    return m_policy;
}

void UCTNode::set_policy(float policy) {
    m_policy = policy;
}

float UCTNode::get_eval_variance(float default_var) const {
    return m_visits > 1 ? m_squared_eval_diff / (m_visits - 1) : default_var;
}

int UCTNode::get_visits() const {
    return m_visits;
}

float UCTNode::get_eval_lcb(int color) const {
    // Lower confidence bound of winrate.
    auto visits = get_visits();
    if (visits < 2) {
        // Return large negative value if not enough visits.
        return -1e6f + visits;
    }
    auto mean = get_raw_eval(color);

    auto stddev = std::sqrt(get_eval_variance(1.0f) / visits);
    auto z = cached_t_quantile(visits - 1);

    return mean - z * stddev;
}

float UCTNode::get_raw_eval(int tomove, int virtual_loss) const {
    auto visits = get_visits() + virtual_loss;
    assert(visits > 0);
    auto blackeval = get_blackevals();
    if (tomove == FastBoard::WHITE) {
        blackeval += static_cast<double>(virtual_loss);
    }
    auto eval = static_cast<float>(blackeval / double(visits));
    if (tomove == FastBoard::WHITE) {
        eval = 1.0f - eval;
    }
    return eval;
}

float UCTNode::get_eval(int tomove) const {
    // Due to the use of atomic updates and virtual losses, it is
    // possible for the visit count to change underneath us. Make sure
    // to return a consistent result to the caller by caching the values.
    return get_raw_eval(tomove, m_virtual_loss);
}

float UCTNode::get_net_eval(int tomove) const {
    if (tomove == FastBoard::WHITE) {
        return 1.0f - m_net_eval;
    }
    return m_net_eval;
}

double UCTNode::get_blackevals() const {
    return m_blackevals;
}

void UCTNode::accumulate_eval(float eval) {
    atomic_add(m_blackevals, double(eval));
}

UCTNode* UCTNode::uct_select_child(int color, bool is_root) {
    (void)is_root;
    wait_expanded();

    // Children are sorted by descending policy.
    // An unvisited child gets the lowest winrate *to the left* .
    // We need the array because an unvisited child can be followed by visited ones.
    // Also, cache everything to minimize threading inconsistencies.
    // This is not paranoia. I tried.
    float winrates[362]; // On the stack. No mallocs.
    int visits[362];
    int idx = -1;
    // Do this as quickly as possible. Ideally we should lock the node.
    for (auto& child : m_children) {
        idx++;
        visits[idx] = child.get_visits();
        if (visits[idx]) {
            winrates[idx] = child.get_eval(color);
        }
    }

    float smallest_winrate = get_net_eval(color); // Important. Do no start with anything else.
    int parentvisits = 0;
    idx = -1;
    for (auto& child : m_children) {
        idx++;
        if (visits[idx] > 0) {
            smallest_winrate = std::min(smallest_winrate, winrates[idx]);
        } else {
            winrates[idx] = smallest_winrate;
        }
        if (child.valid()) {
            parentvisits += visits[idx];
        }
    }

    const auto numerator = std::sqrt(double(parentvisits) *
            std::log(cfg_logpuct * double(parentvisits) + cfg_logconst));

    auto best = static_cast<UCTNodePointer*>(nullptr);
    auto best_value = std::numeric_limits<double>::lowest();

    idx = -1;
    for (auto& child : m_children) {
        idx++;
        if (!child.active()) {
            continue;
        }
        const auto psa = child.get_policy();
        const auto denom = 1.0 + visits[idx];
        const auto puct = cfg_puct * psa * (numerator / denom);
        const auto value = winrates[idx] + puct;
        assert(value > std::numeric_limits<double>::lowest());

        if (value > best_value) {
            if (child.is_inflated() && child->m_expand_state.load() == ExpandState::EXPANDING) {
                // Someone else is expanding this node, never select it
            } else {
                best_value = value;
                best = &child;
            }
        }
    }

    assert(best != nullptr);
    best->inflate();
    return best->get();
}

class NodeComp : public std::binary_function<UCTNodePointer&,
                                             UCTNodePointer&, bool> {
public:
    NodeComp(int color, float lcb_min_visits) : m_color(color),
        m_lcb_min_visits(lcb_min_visits){};

    // WARNING : on very unusual cases this can be called on multithread
    // contexts (e.g., UCTSearch::get_pv()) so beware of race conditions
    bool operator()(const UCTNodePointer& a,
                    const UCTNodePointer& b) {
        auto a_visit = a.get_visits();
        auto b_visit = b.get_visits();

        // Need at least 2 visits for LCB.
        if (m_lcb_min_visits < 2) {
            m_lcb_min_visits = 2;
        }

        // Calculate the lower confidence bound for each node.
        if ((a_visit > m_lcb_min_visits) && (b_visit > m_lcb_min_visits)) {
            auto a_lcb = a.get_eval_lcb(m_color);
            auto b_lcb = b.get_eval_lcb(m_color);

            // Sort on lower confidence bounds
            if (a_lcb != b_lcb) {
                return a_lcb < b_lcb;
            }
        }

        // if visits are not same, sort on visits
        if (a_visit != b_visit) {
            return a_visit < b_visit;
        }

        // neither has visits, sort on policy prior
        if (a_visit == 0) {
            return a.get_policy() < b.get_policy();
        }

        // both have same non-zero number of visits
        return a.get_eval(m_color) < b.get_eval(m_color);
    }
private:
    int m_color;
    float m_lcb_min_visits;
};

void UCTNode::sort_children(int color, float lcb_min_visits) {
    std::stable_sort(rbegin(m_children), rend(m_children), NodeComp(color, lcb_min_visits));
}

UCTNode& UCTNode::get_best_root_child(int color) {
    wait_expanded();

    assert(!m_children.empty());

    auto max_visits = 0;
    for (const auto& node : m_children) {
        max_visits = std::max(max_visits, node.get_visits());
    }

    auto ret = std::max_element(begin(m_children), end(m_children),
                                NodeComp(color, cfg_lcb_min_visit_ratio * max_visits));
    ret->inflate();

    return *(ret->get());
}

size_t UCTNode::count_nodes_and_clear_expand_state() {
    auto nodecount = size_t{0};
    nodecount += m_children.size();
    if (expandable()) {
        m_expand_state = ExpandState::INITIAL;
    }
    for (auto& child : m_children) {
        if (child.is_inflated()) {
            nodecount += child->count_nodes_and_clear_expand_state();
        }
    }
    return nodecount;
}

void UCTNode::invalidate() {
    m_status = INVALID;
}

void UCTNode::set_active(const bool active) {
    if (valid()) {
        m_status = active ? ACTIVE : PRUNED;
    }
}

bool UCTNode::valid() const {
    return m_status != INVALID;
}

bool UCTNode::active() const {
    return m_status == ACTIVE;
}

bool UCTNode::acquire_expanding() {
    auto expected = ExpandState::INITIAL;
    auto newval = ExpandState::EXPANDING;
    return m_expand_state.compare_exchange_strong(expected, newval);
}

void UCTNode::expand_done() {
    auto v = m_expand_state.exchange(ExpandState::EXPANDED);
#ifdef NDEBUG
    (void)v;
#endif
    assert(v == ExpandState::EXPANDING);
}
void UCTNode::expand_cancel() {
    auto v = m_expand_state.exchange(ExpandState::INITIAL);
#ifdef NDEBUG
    (void)v;
#endif
    assert(v == ExpandState::EXPANDING);
}
void UCTNode::wait_expanded() {
    while (m_expand_state.load() == ExpandState::EXPANDING) {}
    auto v = m_expand_state.load();
#ifdef NDEBUG
    (void)v;
#endif
    assert(v == ExpandState::EXPANDED);
}
