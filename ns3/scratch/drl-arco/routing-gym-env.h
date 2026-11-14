/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef DRL_ARCO_ROUTING_GYM_ENV_H
#define DRL_ARCO_ROUTING_GYM_ENV_H

#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/opengym-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/traffic-control-module.h"

#include <cstdint>
#include <map>
#include <string>
#include <utility>
#include <vector>

namespace ns3
{

/** One end of a point-to-point link: the transmitting interface and its counters. */
struct DirectedLink
{
    uint32_t from;
    uint32_t to;
    uint32_t linkIndex;
    uint32_t interface;    //!< IPv4 interface index on `from`
    Ipv4Address nextHopIp; //!< address of `to` on this link
    double bitsPerSecond;
    double propagationSeconds;
    Ptr<Queue<Packet>> queue;
    Ptr<RateErrorModel> rxError; //!< on the receiving device; enabled while the link is down
    uint32_t queueLimit;
    uint64_t lastReceivedBytes;
    uint32_t lastQueueBytes;
    uint32_t lastReceivedPackets;
    uint32_t lastDroppedPackets;
};

/** A flow's FlowMonitor totals at the previous decision step. */
struct FlowTotals
{
    double tx = 0;
    double rx = 0;
    double rxBytes = 0;
    double delaySum = 0;
    double jitterSum = 0;
};

/**
 * Exchanges state and routing decisions with the Python agent at every step.
 *
 * Observation (float box): simTime, then 4 values per directed link (queue fraction,
 * utilization, loss fraction, delay in seconds), then 5 per flow (tx, rx, rxBytes,
 * delaySum, jitterSum, all deltas since the previous step).
 *
 * Action (int32 box): nextHop[n][d] for all node pairs (-1 keeps the current route),
 * then linkUp[l] for all links, then the traffic scale in percent.
 */
class RoutingGymEnv : public OpenGymEnv
{
  public:
    RoutingGymEnv(Time stepTime,
                  NodeContainer nodes,
                  std::vector<DirectedLink> links,
                  std::vector<Ipv4Address> nodeAddress,
                  std::vector<Ptr<OnOffApplication>> apps,
                  std::vector<double> flowRates,
                  Ptr<FlowMonitor> monitor,
                  Ptr<Ipv4FlowClassifier> classifier,
                  uint16_t basePort,
                  uint32_t linkCount);

    static TypeId GetTypeId();
    void DoDispose() override;

    Ptr<OpenGymSpace> GetActionSpace() override;
    Ptr<OpenGymSpace> GetObservationSpace() override;
    bool GetGameOver() override;
    Ptr<OpenGymDataContainer> GetObservation() override;
    float GetReward() override;
    std::string GetExtraInfo() override;
    bool ExecuteActions(Ptr<OpenGymDataContainer> action) override;

  private:
    void ScheduleNextStep();
    void SetNextHop(uint32_t node, uint32_t dest, int32_t hop);
    void SetLinkState(uint32_t link, bool up);
    uint32_t ObservationSize() const;

    Time m_stepTime;
    NodeContainer m_nodes;
    std::vector<DirectedLink> m_links;
    std::vector<Ipv4Address> m_nodeAddress;
    std::vector<Ptr<OnOffApplication>> m_apps;
    std::vector<double> m_flowRates;
    Ptr<FlowMonitor> m_monitor;
    Ptr<Ipv4FlowClassifier> m_classifier;
    uint16_t m_basePort;
    uint32_t m_linkCount;
    int32_t m_scalePercent;

    std::vector<Ptr<Ipv4StaticRouting>> m_routing;
    std::map<std::pair<uint32_t, uint32_t>, uint32_t> m_portOf; //!< (from, to) to m_links index
    std::vector<std::vector<int32_t>> m_fib;
    std::vector<bool> m_linkUp;
    std::vector<FlowTotals> m_flowTotals;
};

} // namespace ns3

#endif // DRL_ARCO_ROUTING_GYM_ENV_H
