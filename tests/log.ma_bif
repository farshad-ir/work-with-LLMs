#ifndef __MA_BIFURCATION_MQH__
#define __MA_BIFURCATION_MQH__

// ------------------------------------------------------------
// CMABifurcation
// Branch-tracking direction detector (MA_Bifurcation algorithm).
// The input price (one MA, or an average of several MAs) is supplied
// by the caller through AddPoint(); this class never reads the chart.
// Direction: +1 up, -1 down, 0 unknown.
// ------------------------------------------------------------

struct MABranch
{
   int    id;
   int    pointCount;
   double previousPrice;
   double lastPrice;
   int    direction;      // 0 until the second distinct price arrives
   int    lastSeenStep;
};

class CMABifurcation
{
private:
   MABranch m_branches[];
   int      m_minWaiting;
   int      m_maxWaiting;
   int      m_step;
   int      m_nextBranchId;

   int      m_direction;        // result of the latest AddPoint (may be 0)
   int      m_lastKnown;        // last non-zero result
   bool     m_reversed;         // did the latest AddPoint flip the known direction?

   int PriceDirection(const double a,const double b)
   {
      if(b>a) return 1;
      if(b<a) return -1;
      return 0;
   }

   // N=2 -> 2, N=3 -> 2, N=4 -> 3, N=5 -> 4, N>=6 -> 5 (limits configurable)
   int WaitingPeriod(const int activeCount)
   {
      int waiting=activeCount-1;
      if(waiting<m_minWaiting) waiting=m_minWaiting;
      if(waiting>m_maxWaiting) waiting=m_maxWaiting;
      return waiting;
   }

   // One-point branch accepts anything; a directional branch must stay monotonic.
   bool CanAppend(const MABranch &b,const double price)
   {
      if(b.pointCount<2 || b.direction==0) return true;
      if(b.direction>0) return price>=b.lastPrice;
      return price<=b.lastPrice;
   }

   void Append(MABranch &b,const double price)
   {
      b.previousPrice=b.lastPrice;
      b.lastPrice=price;
      if(b.direction==0) b.direction=PriceDirection(b.previousPrice,b.lastPrice);
      b.pointCount++;
      b.lastSeenStep=m_step;
   }

   int Create(const double price)
   {
      int n=ArraySize(m_branches);
      if(ArrayResize(m_branches,n+1)!=n+1) return -1;
      m_branches[n].id=m_nextBranchId++;
      m_branches[n].pointCount=1;
      m_branches[n].previousPrice=price;
      m_branches[n].lastPrice=price;
      m_branches[n].direction=0;
      m_branches[n].lastSeenStep=m_step;
      return n;
   }

   void Remove(const int idx)
   {
      int n=ArraySize(m_branches);
      if(idx<0 || idx>=n) return;
      for(int i=idx;i<n-1;i++) m_branches[i]=m_branches[i+1];
      ArrayResize(m_branches,n-1);
   }

   // A branch that received no point within its waiting period is dropped.
   void ExpireInactive()
   {
      int i=0;
      while(i<ArraySize(m_branches))
      {
         int waiting=WaitingPeriod(ArraySize(m_branches));
         if(m_step-m_branches[i].lastSeenStep>=waiting) Remove(i);
         else i++;
      }
   }

public:
   CMABifurcation()
   {
      m_minWaiting=2; m_maxWaiting=5;
      Reset();
   }

   void Configure(const int minWaitingPoints=2,const int maxWaitingPoints=5)
   {
      m_minWaiting=MathMax(1,minWaitingPoints);
      m_maxWaiting=MathMax(m_minWaiting,maxWaitingPoints);
   }

   void Reset()
   {
      ArrayResize(m_branches,0);
      m_step=0; m_nextBranchId=1;
      m_direction=0; m_lastKnown=0; m_reversed=false;
   }

   // Feed one new point; returns the overall direction (+1 / -1 / 0).
   int AddPoint(const double price)
   {
      m_step++;

      bool assigned=false;
      for(int i=0;i<ArraySize(m_branches);i++)
      {
         if(!CanAppend(m_branches[i],price)) continue;
         Append(m_branches[i],price);
         assigned=true;
         break;
      }
      if(!assigned)
      {
         if(Create(price)<0) return m_direction;   // allocation failed; keep old state
      }

      ExpireInactive();

      int rising=0,falling=0;
      for(int j=0;j<ArraySize(m_branches);j++)
      {
         if(m_branches[j].pointCount<2) continue;
         if(m_branches[j].direction>0) rising++;
         else if(m_branches[j].direction<0) falling++;
      }

      int dir=0;
      if(rising>falling) dir=1;
      else if(falling>rising) dir=-1;

      m_reversed=(dir!=0 && m_lastKnown!=0 && dir!=m_lastKnown);
      m_direction=dir;
      if(dir!=0) m_lastKnown=dir;
      return dir;
   }

   int  Direction()          { return m_direction; }   // latest result, may be 0
   int  LastKnownDirection() { return m_lastKnown; }   // last non-zero result
   bool JustReversed()       { return m_reversed; }    // latest point flipped the known direction
   int  BranchCount()        { return ArraySize(m_branches); }
   int  Step()               { return m_step; }
};

#endif // __MA_BIFURCATION_MQH__
