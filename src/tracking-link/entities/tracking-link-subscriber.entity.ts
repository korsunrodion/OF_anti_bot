import { Column, Entity, PrimaryColumn } from 'typeorm';

export type RiskLevel = 'no risk' | 'low' | 'high' | 'very high' | 'extreme';

@Entity('tracking_links_subscriber')
export class TrackingLinkSubscriber {
  @PrimaryColumn()
  id: string;

  @Column()
  trackingLinkId: string;

  @Column()
  username: string;

  @Column()
  userId: number;

  @Column()
  subscriptionDate: string;

  @Column()
  riskLevel: RiskLevel;
}
