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

  @Column({ default: 0 })
  totalChargebacks: number;

  @Column({ nullable: true })
  avatarUrl: string;

  @Column({ nullable: true })
  header: string;

  @Column({ nullable: true })
  isOnlineMatchesSubscription: boolean;

  @Column({ nullable: true })
  isReadingMessages: boolean;

  @Column({ nullable: true })
  riskLevel: RiskLevel;

  @Column({ default: false })
  isProcessed: boolean;

  @Column({ default: false })
  isInternalData: boolean;
}
